import re
from datetime import timedelta
from urllib.parse import quote
from django.db import transaction
from django.db.models import Q, Exists, OuterRef, Subquery, Count
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from apps.accounts.models import User, UserFollow
from apps.community_ai.services import enqueue_direct_reply
from apps.core.http import read_json, InvalidJSON
from apps.core.permissions import require_user
from apps.core.responses import json_ok, json_error
from apps.murmurs.models import MurmurBlock
from apps.notifications.models import Notification
from apps.notifications.services import notify_message
from .models import PrivateMessage

# 关注对方的人在对方回复前最多能发几条问候；被关注的人回复后不再限制。
FOLLOWER_MESSAGE_LIMIT = 3


def private(response):
    response["Cache-Control"] = "no-store"
    return response


def identity(user):
    return {"username": user.username, "display_name": user.display_name or user.username, "avatar_url": user.avatar_url}


def blocked(a, b):
    return MurmurBlock.objects.filter(Q(username=a, blocked_username=b) | Q(username=b, blocked_username=a)).exists()


def pair(user, peer):
    return PrivateMessage.objects.filter(Q(sender=user, recipient=peer) | Q(sender=peer, recipient=user))


def send_policy(sender, peer):
    """Compose policy for sender → peer.

    Strangers and fans are capped at FOLLOWER_MESSAGE_LIMIT messages until the
    peer replies. Once the peer replies, or the peer follows the sender (the
    followed person messaging a fan), the thread is unlimited.
    """
    sent = PrivateMessage.objects.filter(sender=sender, recipient=peer).count()
    following = UserFollow.objects.filter(follower=sender, following=peer).exists()
    if PrivateMessage.objects.filter(sender=peer, recipient=sender).exists():
        return {"limited": False, "remaining": None, "total": FOLLOWER_MESSAGE_LIMIT,
                "sent": sent, "following": following, "reason": "replied"}
    if UserFollow.objects.filter(follower=peer, following=sender).exists():
        return {"limited": False, "remaining": None, "total": FOLLOWER_MESSAGE_LIMIT,
                "sent": sent, "following": following, "reason": "followed_by_peer"}
    return {"limited": True, "remaining": max(0, FOLLOWER_MESSAGE_LIMIT - sent), "total": FOLLOWER_MESSAGE_LIMIT,
            "sent": sent, "following": following, "reason": "following" if following else "stranger"}


@require_GET
@require_user
def inbox(request):
    me = request.user
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return json_error("分页参数错误")
    latest = PrivateMessage.objects.filter(Q(sender=me, recipient=OuterRef("pk")) | Q(recipient=me, sender=OuterRef("pk"))).order_by("-id")
    unread = PrivateMessage.objects.filter(sender=OuterRef("pk"), recipient=me, is_read=False).order_by().values("sender").annotate(n=Count("id")).values("n")
    qs = User.objects.annotate(has_chat=Exists(latest), last_id=Subquery(latest.values("id")[:1]),
                               last_content=Subquery(latest.values("content")[:1]),
                               last_at=Subquery(latest.values("created_at")[:1]), unread=Coalesce(Subquery(unread), 0))
    qs = qs.filter(has_chat=True).exclude(pk=me.pk).order_by("-last_id")
    total = qs.count()
    return private(json_ok({"items": [{**identity(user), "preview": user.last_content[:100], "unread": user.unread,
                                       "last_at": user.last_at.isoformat() if user.last_at else ""}
                                      for user in qs[(page-1)*20:page*20]], "page": page, "total": total,
                            "unread": PrivateMessage.objects.filter(recipient=me, is_read=False).count()}))


@require_http_methods(["GET", "POST"])
@require_user
def thread(request, username):
    peer = User.objects.filter(username=username, is_system_generated=False).first()
    if not peer:
        return json_error("用户不存在或暂不支持私信", status=404)
    if peer.pk == request.user.pk:
        return json_error("不能给自己发送私信")
    if request.method == "GET":
        qs = pair(request.user, peer)
        try:
            before = int(request.GET.get("before", 0))
            after = int(request.GET.get("after", 0))
            limit = int(request.GET.get("limit", 30))
            if before < 0 or after < 0 or (before and after) or not 1 <= limit <= 50:
                raise ValueError
        except ValueError:
            return json_error("分页参数错误")
        if before:
            qs = qs.filter(pk__lt=before)
        if after:
            qs = qs.filter(pk__gt=after)
        rows = list(qs.order_by("id" if after else "-id")[:limit + 1])
        more = len(rows) > limit
        rows = rows[:limit]
        if not after:
            rows.reverse()
        return private(json_ok({"me": identity(request.user), "peer": identity(peer), "blocked": blocked(request.user.username, username),
                                "policy": send_policy(request.user, peer),
                                "items": [{"id": row.pk, "content": row.content, "mine": row.sender_id == request.user.pk,
                                           "created_at": row.created_at.isoformat(), "is_read": row.is_read} for row in rows],
                                "next_cursor": rows[0].pk if rows and more and not after else None, "has_more": more}))
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("消息格式错误")
    content, key = body.get("content", ""), body.get("client_key", "")
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 2000:
        return json_error("私信须为 1–2000 字")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", key):
        return json_error("消息标识错误，请刷新后重试")
    with transaction.atomic():
        # Serialise sends per account so concurrent clients cannot bypass limits.
        User.objects.select_for_update().get(pk=request.user.pk)
        if blocked(request.user.username, username):
            return json_error("双方存在屏蔽关系，暂时无法发送私信", status=403)
        old = PrivateMessage.objects.filter(sender=request.user, client_key=key).first()
        if old:
            if old.recipient_id != peer.pk or old.content != content.strip():
                return json_error("该消息已处理，请重新发送", status=409)
            return private(json_ok({"id": old.pk, "replayed": True}))
        if PrivateMessage.objects.filter(sender=request.user, created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= 15:
            return json_error("发送过于频繁，请稍后再试", status=429)
        policy = send_policy(request.user, peer)
        if policy["limited"] and policy["remaining"] <= 0:
            return json_error("对方回复前最多只能发送 3 条私信", status=403, policy=policy)
        row = PrivateMessage.objects.create(sender=request.user, recipient=peer, content=content.strip(), client_key=key)
        notify_message(recipient=peer, sender=request.user,
                       count=PrivateMessage.objects.filter(recipient=peer, sender=request.user, is_read=False).count(),
                       link=f"/messages?user={quote(request.user.username, safe='')}")
    # Queued outside the send transaction: an assistant hiccup must never fail a delivered message.
    queued = bool(enqueue_direct_reply(row))
    return private(json_ok({"id": row.pk, "ai_reply_queued": queued}, status=201))


@require_POST
@require_user
def mark_read(request, username):
    try:
        upto = read_json(request).get("upto")
    except InvalidJSON:
        return json_error("请求格式错误")
    if type(upto) is not int or upto < 1:
        return json_error("消息标识错误")
    with transaction.atomic():
        PrivateMessage.objects.filter(recipient=request.user, sender__username=username, pk__lte=upto).update(is_read=True)
        if not PrivateMessage.objects.filter(recipient=request.user, sender__username=username, is_read=False).exists():
            Notification.objects.filter(recipient=request.user, actor_username=username, type="message", is_read=False).update(is_read=True)
    return private(json_ok({"read": True}))
