"""Public microblog feed with authenticated writes and existing community identities."""
from datetime import timedelta
from functools import wraps
import re
import uuid

from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.accounts.models import User
from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin
from apps.core.responses import json_error, json_ok
from apps.forum.models import ForumImage, ForumModerationAction
from apps.notifications.models import Notification
from apps.notifications.services import notify
from .models import Murmur, MurmurBlock, MurmurComment, MurmurImage, MurmurLike, MurmurReport, timestamp
from .services import actor, authors_payload, can_moderate, feed_queryset, serialize_posts, visible_posts

REPORT_REASONS = {"spam", "abuse", "copyright", "other"}


class InputError(ValueError):
    pass


def api_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except InvalidJSON:
            return json_error("请求格式有误，请重试")
        except InputError as exc:
            return json_error(str(exc))
    return wrapped


def text(body, name, limit, default=""):
    value = body.get(name, default)
    if not isinstance(value, str):
        raise InputError("请输入有效的文字内容")
    value = value.strip()
    if len(value) > limit:
        raise InputError(f"最多支持 {limit} 个字")
    return value


def client_key(body):
    value = body.get("client_key", "") or uuid.uuid4().hex
    if not isinstance(value, str) or not re.fullmatch(r"[\w-]{8,64}", value, flags=re.ASCII):
        raise InputError("发布标识无效，请刷新页面重试")
    return value


def cursor(request, name="before"):
    raw = request.GET.get(name, "")
    if not raw:
        return None
    if not raw.isascii() or not raw.isdigit() or len(raw) > 18 or int(raw) < 1:
        raise InputError("分页参数无效")
    return int(raw)


def audit(request, target, *, comment=False, note=""):
    ForumModerationAction.objects.create(
        target_type="murmur_comment" if comment else "murmur",
        target_id=target.pk,
        action="content_removed",
        admin_username=actor(request),
        note=note or "管理员删除碎碎念内容",
    )


def send_notification(post, username, type_, content=""):
    if username == post.author_username:
        return
    recipient = User.objects.filter(username=post.author_username).first()
    if not recipient:
        return
    if MurmurBlock.objects.filter(username=post.author_username, blocked_username=username).exists():
        return
    link = f"/murmurs?post={post.pk}"
    # A repeated unlike/like must not fill the author's inbox.
    if type_ == "like" and Notification.objects.filter(recipient=recipient, type="like", link=link, actor_username=username).exists():
        return
    name = User.objects.filter(username=username).values_list("display_name", flat=True).first() or username
    notify(recipient=recipient, type_=type_, title=f"{name}{'赞了你的碎碎念' if type_ == 'like' else '评论了你的碎碎念'}",
           body=content or post.content[:160] or "分享的图片", link=link, actor_username=username)


@require_GET
def session(request):
    username = actor(request)
    return json_ok({
        "loggedIn": bool(username),
        "profile": authors_payload([username]).get(username) if username else None,
        "can_moderate": can_moderate(request),
    })


@require_http_methods(["GET", "POST"])
@api_errors
def posts(request):
    username = actor(request)
    if request.method == "GET":
        qs = feed_queryset(username)
        author = request.GET.get("author", "").strip()
        if request.GET.get("scope") == "mine":
            if not username:
                return json_error("请先登录", status=401)
            author = username
        if author:
            qs = qs.filter(author_username=author)
        before = cursor(request)
        if before:
            qs = qs.filter(pk__lt=before)
        rows = list(qs[:21])
        more = len(rows) > 20
        rows = rows[:20]
        return json_ok({"items": serialize_posts(rows, username, can_moderate(request)), "next_cursor": rows[-1].pk if rows and more else None})
    if not username:
        return json_error("登录后就可以发布碎碎念", status=401)
    body = read_json(request)
    content = text(body, "content", 1000)
    ids = body.get("images", [])
    if not isinstance(ids, list) or len(ids) > 9 or any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
        return json_error("请选择最多 9 张不同的图片")
    if not content and not ids:
        return json_error("写点什么，或分享一张图片吧")
    if ForumImage.objects.filter(pk__in=ids, uploader_username=username).count() != len(ids):
        return json_error("图片不存在或不属于你，请重新上传")
    key = client_key(body)
    with transaction.atomic():
        existing = Murmur.objects.filter(author_username=username, client_key=key).first()
        if existing:
            if existing.is_deleted or existing.content != content or list(existing.attachments.values_list("image_id", flat=True)) != ids:
                return json_error("这次发布已经处理过，请重新发布", status=409)
            row, created = existing, False
        else:
            since = (timezone.now() - timedelta(seconds=30)).isoformat()
            if Murmur.objects.filter(author_username=username, created_at__gte=since).exists():
                return json_error("发布得有点快，稍等 30 秒再分享吧", status=429)
            row = Murmur.objects.create(author_username=username, content=content, client_key=key)
            MurmurImage.objects.bulk_create([MurmurImage(murmur=row, image_id=i, position=p) for p, i in enumerate(ids)])
            created = True
    item = serialize_posts([feed_queryset(username).get(pk=row.pk)], username, can_moderate(request))[0]
    return json_ok({"item": item, "replayed": not created}, status=201 if created else 200)


@require_http_methods(["GET", "DELETE"])
@api_errors
def post_detail(request, post_id):
    username = actor(request)
    if request.method == "GET":
        row = feed_queryset(username).filter(pk=post_id).first()
        if not row:
            return json_error("这条碎碎念不存在、已删除或已被屏蔽", status=404)
        return json_ok({"item": serialize_posts([row], username, can_moderate(request))[0]})
    if not username:
        return json_error("请先登录", status=401)
    with transaction.atomic():
        row = Murmur.objects.select_for_update().filter(pk=post_id).first()
        if not row:
            return json_error("碎碎念不存在", status=404)
        if row.author_username != username and not can_moderate(request):
            return json_error("只能删除自己的碎碎念", status=403)
        if not row.is_deleted:
            row.is_deleted = True
            row.save(update_fields=["is_deleted"])
            if row.author_username != username:
                audit(request, row)
    return json_ok({"deleted": True})


@require_POST
@api_errors
def like(request, post_id):
    username = actor(request)
    if not username:
        return json_error("登录后就可以点赞", status=401)
    body = read_json(request)
    desired = body.get("liked")
    if not isinstance(desired, bool):
        return json_error("点赞状态无效")
    with transaction.atomic():
        post = visible_posts(username).select_for_update().filter(pk=post_id).first()
        if not post:
            return json_error("这条碎碎念已不可见", status=404)
        if desired:
            _, created = MurmurLike.objects.get_or_create(murmur=post, username=username)
            if created:
                transaction.on_commit(lambda: send_notification(post, username, "like"))
        else:
            MurmurLike.objects.filter(murmur=post, username=username).delete()
        count = post.likes.count()
    return json_ok({"liked": desired, "like_count": count})


def comment_payload(row, authors, username, moderator):
    return {"id": row.pk, "content": row.content, "author": authors[row.author_username], "created_at": row.created_at,
            "can_delete": row.author_username == username or moderator, "is_own": row.author_username == username}


@require_http_methods(["GET", "POST"])
@api_errors
def comments(request, post_id):
    username = actor(request)
    post = visible_posts(username).filter(pk=post_id).first()
    if not post:
        return json_error("这条碎碎念已不可见", status=404)
    if request.method == "GET":
        qs = post.comments.filter(is_deleted=False)
        if username:
            qs = qs.exclude(author_username__in=MurmurBlock.objects.filter(username=username).values("blocked_username"))
        after = cursor(request, "after")
        if after:
            qs = qs.filter(pk__gt=after)
        rows = list(qs[:31])
        more = len(rows) > 30
        rows = rows[:30]
        authors = authors_payload([row.author_username for row in rows])
        moderator = can_moderate(request)
        return json_ok({"items": [comment_payload(row, authors, username, moderator) for row in rows],
                        "next_cursor": rows[-1].pk if rows and more else None})
    if not username:
        return json_error("登录后就可以评论", status=401)
    body = read_json(request)
    content = text(body, "content", 500)
    if not content:
        return json_error("写点什么再发送吧")
    key = client_key(body)
    with transaction.atomic():
        # Lock the parent so deleting a post cannot leave a new visible comment.
        if not Murmur.objects.select_for_update().filter(pk=post_id, is_deleted=False).exists():
            return json_error("这条碎碎念已删除", status=404)
        existing = MurmurComment.objects.filter(author_username=username, client_key=key).first()
        if existing:
            if existing.is_deleted or existing.murmur_id != post_id or existing.content != content:
                return json_error("这次评论已经处理过，请重新发送", status=409)
            row, created = existing, False
        else:
            since = (timezone.now() - timedelta(seconds=5)).isoformat()
            if MurmurComment.objects.filter(author_username=username, created_at__gte=since).exists():
                return json_error("评论得有点快，请稍等 5 秒", status=429)
            row = MurmurComment.objects.create(murmur=post, author_username=username, content=content, client_key=key)
            created = True
            transaction.on_commit(lambda: send_notification(post, username, "reply", content))
        count = post.comments.filter(is_deleted=False).count()
    return json_ok({"item": comment_payload(row, authors_payload([username]), username, can_moderate(request)),
                    "comment_count": count, "replayed": not created}, status=201 if created else 200)


@require_http_methods(["DELETE"])
def comment_detail(request, comment_id):
    username = actor(request)
    if not username:
        return json_error("请先登录", status=401)
    with transaction.atomic():
        row = MurmurComment.objects.select_for_update().filter(pk=comment_id, murmur__is_deleted=False).first()
        if not row:
            return json_error("评论不存在", status=404)
        if row.author_username != username and not can_moderate(request):
            return json_error("只能删除自己的评论", status=403)
        if not row.is_deleted:
            row.is_deleted = True
            row.save(update_fields=["is_deleted"])
            if row.author_username != username:
                audit(request, row, comment=True)
        count = row.murmur.comments.filter(is_deleted=False).count()
    return json_ok({"deleted": True, "comment_count": count})


@require_http_methods(["GET", "POST", "DELETE"])
@api_errors
def blocks(request):
    username = actor(request)
    if not username:
        return json_error("请先登录", status=401)
    if request.method == "GET":
        names = list(MurmurBlock.objects.filter(username=username).values_list("blocked_username", flat=True))
        return json_ok({"items": list(authors_payload(names).values())})
    target = text(read_json(request), "username", 150)
    if not target or target == username:
        return json_error("请选择其他用户")
    if request.method == "DELETE":
        MurmurBlock.objects.filter(username=username, blocked_username=target).delete()
    else:
        # Admin-only community accounts may not have a matching user row.
        if not User.objects.filter(username=target).exists() and not Murmur.objects.filter(author_username=target).exists():
            return json_error("用户不存在", status=404)
        MurmurBlock.objects.get_or_create(username=username, blocked_username=target)
    return json_ok({"blocked": request.method == "POST"})


def create_report(request, post_id, comment=None):
    username = actor(request)
    if not username:
        return json_error("登录后就可以举报", status=401)
    post = visible_posts(username).filter(pk=post_id).first()
    if not post:
        return json_error("这条碎碎念已不可见", status=404)
    body = read_json(request)
    reason = text(body, "reason", 32, "other")
    details = text(body, "details", 500)
    if reason not in REPORT_REASONS:
        return json_error("请选择有效的举报原因")
    key = f"comment:{comment.pk}" if comment else f"post:{post.pk}"
    row, created = MurmurReport.objects.get_or_create(target_key=key, reporter_username=username,
        defaults={"murmur": post, "comment": comment, "reason": reason, "details": details})
    return json_ok({"reported": True, "duplicate": not created}, status=201 if created else 200)


@require_POST
@api_errors
def report(request, post_id):
    return create_report(request, post_id)


@require_POST
@api_errors
def report_comment(request, comment_id):
    row = MurmurComment.objects.filter(pk=comment_id, is_deleted=False, murmur__is_deleted=False).first()
    if not row:
        return json_error("评论不存在", status=404)
    return create_report(request, row.murmur_id, row)


@require_admin(level=2)
@require_GET
@api_errors
def admin_reports(request):
    status = request.GET.get("status", "pending")
    if status not in {"pending", "resolved", "rejected", "all"}:
        return json_error("举报状态无效")
    qs = MurmurReport.objects.select_related("murmur", "comment").prefetch_related("murmur__attachments__image").order_by("-id")
    if status != "all":
        qs = qs.filter(status=status)
    before = cursor(request)
    if before:
        qs = qs.filter(pk__lt=before)
    rows = list(qs[:31])
    more = len(rows) > 30
    rows = rows[:30]
    items = []
    for row in rows:
        target = row.comment or row.murmur
        items.append({"id": row.pk, "post_id": row.murmur_id, "comment_id": row.comment_id,
            "content": target.content, "author_username": target.author_username,
            "images": [] if row.comment_id else [{"url": f"/api/forum/images/{a.image_id}"} for a in row.murmur.attachments.all()],
            "reporter_username": row.reporter_username, "reason": row.reason, "details": row.details, "status": row.status,
            "created_at": row.created_at, "reviewer_username": row.reviewer_username, "review_note": row.review_note,
            "removed": target.is_deleted or row.murmur.is_deleted})
    return json_ok({"items": items, "next_cursor": rows[-1].pk if rows and more else None})


@require_admin(level=2)
@require_POST
@api_errors
def review_report(request, report_id):
    body = read_json(request)
    decision = text(body, "decision", 16)
    note = text(body, "note", 500)
    if decision not in {"resolved", "rejected"} or not isinstance(body.get("remove", False), bool):
        return json_error("处理方式无效")
    remove = decision == "resolved" and body.get("remove", False)
    with transaction.atomic():
        row = MurmurReport.objects.select_for_update().select_related("murmur", "comment").filter(pk=report_id).first()
        if not row:
            return json_error("举报不存在", status=404)
        if row.status != "pending":
            return json_ok({"status": row.status, "replayed": True})
        if remove:
            target = row.comment or row.murmur
            target.is_deleted = True
            target.save(update_fields=["is_deleted"])
            audit(request, target, comment=bool(row.comment_id), note=note or "举报处理下线")
        row.status = decision
        row.reviewer_username = request.kflow_admin["username"]
        row.review_note = note
        row.reviewed_at = timestamp()
        row.save(update_fields=["status", "reviewer_username", "review_note", "reviewed_at"])
    return json_ok({"status": decision, "removed": remove})
