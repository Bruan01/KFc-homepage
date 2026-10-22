"""Community follow relationships shared by profiles and the murmurs composer."""
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from urllib.parse import quote

from apps.core.responses import json_error, json_ok
from apps.murmurs.models import MurmurBlock
from apps.murmurs.services import actor
from .models import User, UserFollow
from .official import official_account_id


def blocked_names(username):
    return set(MurmurBlock.objects.filter(Q(username=username) | Q(blocked_username=username)).values_list("username", flat=True)) | set(
        MurmurBlock.objects.filter(username=username).values_list("blocked_username", flat=True))


def social_payload(target, viewer):
    return {
        "username": target.username,
        "is_official": target.pk == official_account_id(),
        "can_view_connections": bool(viewer and viewer == target.username),
        "following_count": target.following_edges.count(),
        "follower_count": target.follower_edges.count(),
        "is_following": UserFollow.objects.filter(follower__username=viewer, following=target).exists() if viewer else False,
        "follows_you": UserFollow.objects.filter(follower=target, following__username=viewer).exists() if viewer else False,
    }


@require_GET
def official_identity(request):
    account = User.objects.filter(pk=official_account_id(), is_system_generated=False).first()
    # Only public identity; never expose managed follower targets or AI settings.
    return json_ok({"account": {
        "username": account.username,
        "display_name": account.display_name.strip() or account.username,
        "profile_url": f"/forum/user/{quote(account.username, safe='')}",
    } if account else None})


@require_GET
def social(request, username):
    target = User.objects.filter(username=username).first()
    if not target:
        return json_error("用户不存在", status=404)
    return json_ok(social_payload(target, actor(request)))


@require_http_methods(["POST", "DELETE"])
def follow(request, username):
    viewer = actor(request)
    user = User.objects.filter(username=viewer).first() if viewer else None
    if not user:
        return json_error("请先登录用户账号", status=401)
    target = User.objects.filter(username=username).first()
    if not target:
        return json_error("用户不存在", status=404)
    if user.pk == target.pk:
        return json_error("不能关注自己")
    with transaction.atomic():
        if request.method == "DELETE":
            UserFollow.objects.filter(follower=user, following=target).delete()
        else:
            if username in blocked_names(viewer):
                return json_error("已屏蔽的用户无法关注", status=403)
            UserFollow.objects.get_or_create(follower=user, following=target, defaults={"created_at": timezone.now().isoformat()})
    return json_ok(social_payload(target, viewer))


@require_GET
def connections(request, username, kind):
    viewer = actor(request)
    if kind == "mentions":
        if not viewer:
            return json_error("请先登录", status=401)
        username = viewer
    elif not viewer:
        return json_error("请先登录查看自己的关注和粉丝", status=401)
    elif viewer != username:
        return json_error("关注和粉丝列表仅本人可查看", status=403)
    target = User.objects.filter(username=username).first()
    if not target:
        return json_error("用户不存在", status=404)
    qs = User.objects.filter(following_edges__following=target) if kind == "followers" else User.objects.filter(follower_edges__follower=target)
    if viewer:
        qs = qs.exclude(username__in=blocked_names(viewer))
    query = request.GET.get("q", "").strip()[:150]
    if query:
        qs = qs.filter(Q(username__icontains=query) | Q(display_name__icontains=query))
    raw_after = request.GET.get("after", "")
    if raw_after:
        if not raw_after.isascii() or not raw_after.isdigit() or len(raw_after) > 18:
            return json_error("分页参数无效")
        qs = qs.filter(pk__gt=int(raw_after))
    rows = list(qs.annotate(is_following=Exists(UserFollow.objects.filter(follower__username=viewer, following_id=OuterRef("pk")))).order_by("pk")[:21])
    official_id = official_account_id()
    return json_ok({
        "items": [{"username": row.username, "display_name": row.display_name.strip() or row.username,
                   "avatar_url": row.avatar_url, "is_following": row.is_following, "is_official": row.pk == official_id} for row in rows[:20]],
        "next_cursor": rows[19].pk if len(rows) > 20 else None,
    })
