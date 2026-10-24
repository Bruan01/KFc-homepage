"""Public microblog feed with authenticated writes and existing community identities."""
from datetime import datetime, timedelta
from functools import wraps
import io
from pathlib import Path
import re
import uuid

from django.core.files.base import ContentFile
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.accounts.models import User
from apps.accounts.mentions import resolve as resolved_mentions, resolve_many, names as mention_names
from apps.community_ai.models import AssistantReplyJob
from apps.community_ai.services import enqueue_reply
from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin
from apps.core.responses import json_error, json_ok
from apps.forum.models import ForumImage, ForumModerationAction
from apps.notifications.models import Notification
from apps.notifications.services import notify
from .models import (
    Murmur, MurmurAppeal, MurmurBlock, MurmurComment, MurmurCommentImage, MurmurImage,
    MurmurLike, MurmurReport, MurmurVideo, timestamp,
)
from .services import (
    actor, appeal_deadline, appeal_window_open, authors_payload, can_moderate,
    feed_queryset, images_payload, moderation_queryset, serialize_posts, video_payload, videos_payload,
    visible_posts,
)
from .mentions import recipients as mention_recipients, send_mentions

REPORT_REASONS = {"spam", "abuse", "copyright", "other"}
VIDEO_MAX_BYTES = 60 * 1024 * 1024
VIDEO_MAX_SECONDS = 30
VIDEO_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
VIDEO_POSTER_MAX_BYTES = 3 * 1024 * 1024


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


def image_ids(body, username, limit):
    ids = body.get("images", [])
    if not isinstance(ids, list) or len(ids) > limit or any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
        raise InputError(f"请选择最多 {limit} 张不同的图片")
    if ForumImage.objects.filter(pk__in=ids, uploader_username=username).count() != len(ids):
        raise InputError("图片不存在或不属于你，请重新上传")
    return ids


def video_ref(body, username):
    raw = body.get("video")
    if raw in (None, "", 0):
        return None
    if type(raw) is not int or raw <= 0:
        raise InputError("视频参数无效")
    video = MurmurVideo.objects.filter(pk=raw, uploader_username=username, murmur__isnull=True).first()
    if not video:
        raise InputError("视频不存在或已经发布过，请重新上传")
    return video


def cleanup_stale_videos(username):
    """Abandoned uploads (selected then cancelled) never attach to a post."""
    cutoff = timezone.now() - timedelta(days=7)
    stale = MurmurVideo.objects.filter(uploader_username=username, murmur__isnull=True, created_at__lt=cutoff)[:20]
    for video in stale:
        for field in (video.file, video.poster):
            if field:
                field.delete(save=False)
        video.delete()


def cursor(request, name="before"):
    raw = request.GET.get(name, "")
    if not raw:
        return None
    if not raw.isascii() or not raw.isdigit() or len(raw) > 18 or int(raw) < 1:
        raise InputError("分页参数无效")
    return int(raw)


def audit(request, target, *, comment=False, note="", action="content_removed"):
    ForumModerationAction.objects.create(
        target_type="murmur_comment" if comment else "murmur",
        target_id=target.pk,
        action=action,
        admin_username=actor(request),
        note=note or "管理员删除碎碎念内容",
    )


def notify_user(username, title, body="", link="", actor_username=""):
    recipient = User.objects.filter(username=username).first()
    if recipient:
        notify(recipient=recipient, type_="system", title=title, body=body, link=link, actor_username=actor_username)


def parse_target(raw):
    if not isinstance(raw, str) or ":" not in raw:
        raise InputError("申诉对象无效")
    kind, _, ident = raw.partition(":")
    if kind not in {"post", "comment"} or not ident.isascii() or not ident.isdigit() or int(ident) < 1:
        raise InputError("申诉对象无效")
    return kind, int(ident)


def target_key(kind, pk):
    return f"{kind}:{pk}"


def deadline_label(value):
    try:
        return timezone.localtime(datetime.fromisoformat(value)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return value


def mark_deleted(target, admin_username, note):
    target.is_deleted = True
    target.deleted_at = timestamp()
    target.deleted_by = admin_username
    target.deletion_reason = note
    target.appeal_deadline = appeal_deadline()
    target.restored_at = ""
    target.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason", "appeal_deadline", "restored_at"])


def notify_removal(target, *, comment, reviewer):
    kind = "comment" if comment else "post"
    label = "评论" if comment else "碎碎念"
    notify_user(
        target.author_username,
        f"你的{label}被删除，可在限期内申诉",
        f"因举报核实，内容已下线。可在 {deadline_label(target.appeal_deadline)} 前提交申诉。",
        f"/murmurs?appeal={target_key(kind, target.pk)}",
        actor_username=reviewer,
    )


def notify_report_result(reporter_username, decision, removed, note, post_id, appeal_deadline_value=""):
    if decision == "rejected":
        title, body = "你提交的举报已驳回", "管理员复核后未认定违规，内容已保留。"
    elif removed:
        title = "你提交的举报已处理：内容已下线"
        body = "你举报的内容已下线。申诉仅对内容作者开放。"
        if appeal_deadline_value:
            body = f"你举报的内容已下线。申诉仅对内容作者开放，作者可在 {deadline_label(appeal_deadline_value)} 前提交申诉。"
    else:
        title, body = "你提交的举报已处理：内容保留", "管理员复核后未下线内容。"
    if note:
        body = f"{body} 处理备注：{note}"
    notify_user(reporter_username, title, body, "" if removed else f"/murmurs?post={post_id}")


def appeal_payload(row):
    return {"id": row.pk, "status": row.status, "reason": row.reason, "created_at": row.created_at,
            "reviewer_username": row.reviewer_username, "review_note": row.review_note,
            "reviewed_at": row.reviewed_at}


def send_notification(post, username, type_, content="", *, recipient_username=None, reply_to_comment=False):
    recipient_username = recipient_username or post.author_username
    if username == recipient_username:
        return
    recipient = User.objects.filter(username=recipient_username).first()
    if not recipient:
        return
    if MurmurBlock.objects.filter(username=recipient_username, blocked_username=username).exists():
        return
    link = f"/murmurs?post={post.pk}"
    # A repeated unlike/like must not fill the author's inbox.
    if type_ == "like" and Notification.objects.filter(recipient=recipient, type="like", link=link, actor_username=username).exists():
        return
    name = User.objects.filter(username=username).values_list("display_name", flat=True).first() or username
    action = "回复了你的评论" if reply_to_comment else "赞了你的碎碎念" if type_ == "like" else "评论了你的碎碎念"
    notify(recipient=recipient, type_=type_, title=f"{name}{action}",
           body=content or post.content[:160] or "分享的图片", link=link, actor_username=username)


def send_comment_notifications(post, username, content, parent, mentioned=()):
    recipients = {post.author_username: False}
    if parent:
        recipients[parent.author_username] = True
    for recipient, is_reply in recipients.items():
        if recipient in mentioned:
            continue
        send_notification(post, username, "reply", content or "发送了图片或表情包",
                          recipient_username=recipient, reply_to_comment=is_reply)


@require_GET
def session(request):
    username = actor(request)
    profile = authors_payload([username]).get(username) if username else None
    if profile:
        # 发布卡片用它做背景，和「我的主页」共用同一张封面。
        profile["background_url"] = User.objects.filter(username=username).values_list("background_url", flat=True).first() or ""
    return json_ok({
        "loggedIn": bool(username),
        "profile": profile,
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
        if any(key in request.GET for key in ("page", "start", "end", "unread")):
            from .feed import page_feed
            return page_feed(request, qs, username)
        # A pinned item can be older than every normal item. Keep its position
        # in the cursor so crossing into the normal feed never skips newer IDs.
        raw_before = request.GET.get("before", "")
        if raw_before.startswith("p:"):
            raw_id = raw_before[2:]
            if not raw_id.isascii() or not raw_id.isdigit() or len(raw_id) > 18 or int(raw_id) < 1:
                raise InputError("分页参数无效")
            qs = qs.filter(Q(is_pinned=True, pk__lt=int(raw_id)) | Q(is_pinned=False))
        else:
            before = cursor(request)
            if before:
                qs = qs.filter(is_pinned=False, pk__lt=before)
        rows = list(qs.order_by("-is_pinned", "-id")[:21])
        more = len(rows) > 20
        rows = rows[:20]
        next_cursor = None
        if rows and more:
            next_cursor = f"p:{rows[-1].pk}" if rows[-1].is_pinned else rows[-1].pk
        return json_ok({"items": serialize_posts(rows, username), "next_cursor": next_cursor})
    if not username:
        return json_error("登录后就可以发布碎碎念", status=401)
    body = read_json(request)
    content = text(body, "content", 1000)
    ids = image_ids(body, username, 9)
    video = video_ref(body, username)
    if not content and not ids and not video:
        return json_error("写点什么，或分享一张图片/视频吧")
    key = client_key(body)
    ai_job = None
    with transaction.atomic():
        existing = Murmur.objects.filter(author_username=username, client_key=key).first()
        if existing:
            if (existing.is_deleted or existing.content != content
                    or list(existing.attachments.values_list("image_id", flat=True)) != ids
                    or list(existing.videos.values_list("pk", flat=True)) != ([video.pk] if video else [])):
                return json_error("这次发布已经处理过，请重新发布", status=409)
            row, created = existing, False
        else:
            since = (timezone.now() - timedelta(seconds=30)).isoformat()
            if Murmur.objects.filter(author_username=username, created_at__gte=since).exists():
                return json_error("发布得有点快，稍等 30 秒再分享吧", status=429)
            row = Murmur.objects.create(author_username=username, content=content, client_key=key)
            MurmurImage.objects.bulk_create([MurmurImage(murmur=row, image_id=i, position=p) for p, i in enumerate(ids)])
            if video:
                video.murmur = row
                video.save(update_fields=["murmur"])
            created = True
            mentioned = mention_recipients(username, content)
            transaction.on_commit(lambda: send_mentions(row, username, content, mentioned))
            ai_job = enqueue_reply(row)
    item = serialize_posts([feed_queryset(username).get(pk=row.pk)], username)[0]
    return json_ok({"item": item, "replayed": not created, "ai_reply_queued": bool(ai_job and ai_job.status in {"queued", "processing"})}, status=201 if created else 200)


@require_POST
@api_errors
def upload_video(request):
    username = actor(request)
    if not username:
        return json_error("请先登录后再上传视频", status=401)
    upload = request.FILES.get("file")
    if upload is None:
        return json_error("缺少 file 字段")
    if upload.size > VIDEO_MAX_BYTES:
        return json_error("视频最大 60MB", status=413)
    content_type = (upload.content_type or "").lower()
    if content_type not in VIDEO_TYPES:
        return json_error("仅支持 MP4 / WebM 视频")
    try:
        duration = float(request.POST.get("duration", ""))
    except (TypeError, ValueError):
        return json_error("无法读取视频时长")
    if duration <= 0:
        return json_error("无法读取视频时长")
    if duration > VIDEO_MAX_SECONDS + 0.6:
        return json_error(f"视频最长 {VIDEO_MAX_SECONDS} 秒", status=413)
    try:
        width = max(0, int(request.POST.get("width", 0) or 0))
        height = max(0, int(request.POST.get("height", 0) or 0))
    except (TypeError, ValueError):
        width = height = 0

    video = MurmurVideo(
        uploader_username=username, content_type=content_type, file_size=upload.size,
        duration=round(duration, 2), width=width, height=height,
    )
    video.file.save(f"{uuid.uuid4().hex}{VIDEO_TYPES[content_type]}", upload, save=False)
    poster = request.FILES.get("poster")
    if poster is not None and poster.size <= VIDEO_POSTER_MAX_BYTES:
        data = _video_poster_bytes(poster)
        if data:
            video.poster.save(f"{uuid.uuid4().hex}.webp", ContentFile(data), save=False)
    video.save()
    cleanup_stale_videos(username)
    return json_ok({"video": video_payload(video)}, status=201)


def _video_poster_bytes(upload):
    try:
        from PIL import Image, ImageOps

        image = Image.open(upload)
        image.load()
        image = (ImageOps.exif_transpose(image) or image).convert("RGB")
        if max(image.size) > 1280:
            ratio = 1280 / max(image.size)
            image = image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format="WEBP", quality=82, method=6)
        return buf.getvalue()
    except Exception:
        return None


@require_GET
def serve_video(request, video_id):
    video = MurmurVideo.objects.filter(pk=video_id).only("file", "content_type").first()
    if not video or not video.file:
        raise Http404
    try:
        target = Path(video.file.path)
    except (ValueError, NotImplementedError):
        raise Http404 from None
    if not target.is_file():
        raise Http404
    size = target.stat().st_size
    content_type = video.content_type or "video/mp4"
    accel = _xaccel_response(video.file, content_type)
    if accel is not None:
        return accel
    header = (request.headers.get("Range") or "").strip()
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header) if header else None
    if match and (match.group(1) or match.group(2)):
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
        else:
            start = max(0, size - int(match.group(2)))
            end = size - 1
        if start >= size or start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        end = min(end, size - 1)
        response = StreamingHttpResponse(_iter_file(target, start, end), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(end - start + 1)
    else:
        response = StreamingHttpResponse(_iter_file(target, 0, size - 1), content_type=content_type)
        response["Content-Length"] = str(size)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def _xaccel_response(field, content_type):
    """有 nginx（XACCEL_MEDIA_PREFIX 已配置）时把字节流交给 nginx 直发。

    Django 只负责上面已完成的「文件存在吗、类型对不对」，Range/206/416、
    零拷贝和缓存全部由 nginx 处理——视频播放不再占用 Python worker。
    没配前缀（本地开发、或服务器还没上 nginx）时返回 None，走 Django 流式。
    """
    prefix = getattr(settings, "XACCEL_MEDIA_PREFIX", "")
    if not prefix:
        return None
    response = HttpResponse()
    response["X-Accel-Redirect"] = f"{prefix.rstrip('/')}/{field.name}"
    response["Content-Type"] = content_type
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def _iter_file(target, start, end, chunk=256 * 1024):
    remaining = end - start + 1
    with target.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            data = handle.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@require_GET
def serve_video_poster(request, video_id):
    video = MurmurVideo.objects.filter(pk=video_id).only("poster").first()
    if not video or not video.poster:
        raise Http404
    try:
        target = Path(video.poster.path)
    except (ValueError, NotImplementedError):
        raise Http404 from None
    if not target.is_file():
        raise Http404
    accel = _xaccel_response(video.poster, "image/webp")
    if accel is not None:
        return accel
    response = StreamingHttpResponse(_iter_file(target, 0, target.stat().st_size - 1), content_type="image/webp")
    response["Content-Length"] = str(target.stat().st_size)
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@require_http_methods(["GET", "DELETE"])
@api_errors
def post_detail(request, post_id):
    username = actor(request)
    if request.method == "GET":
        row = feed_queryset(username).filter(pk=post_id).first()
        moderation_preview = False
        if not row and can_moderate(request):
            row = moderation_queryset(username).filter(pk=post_id).first()
            moderation_preview = bool(row)
        if not row:
            return json_error("这条碎碎念不存在、已删除或已被屏蔽", status=404)
        return json_ok({"item": serialize_posts([row], username)[0], "moderation_preview": moderation_preview})
    if not username:
        return json_error("请先登录", status=401)
    with transaction.atomic():
        row = Murmur.objects.select_for_update().filter(pk=post_id).first()
        if not row:
            return json_error("碎碎念不存在", status=404)
        if row.author_username != username:
            return json_error("管理员下线内容请通过举报审核", status=403)
        if not row.is_deleted:
            row.is_deleted = True
            row.deleted_at = timestamp()
            row.deleted_by = username
            row.deletion_reason = "作者删除"
            row.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason"])
    return json_ok({"deleted": True})


@require_POST
@require_admin(level=2)
@api_errors
def pin_post(request, post_id):
    desired = read_json(request).get("pinned")
    if type(desired) is not bool:
        return json_error("置顶状态必须是布尔值")
    with transaction.atomic():
        row = Murmur.objects.filter(pk=post_id, is_deleted=False).first()
        if not row:
            return json_error("碎碎念不存在或已删除", status=404)
        changed = Murmur.objects.filter(pk=row.pk, is_deleted=False).exclude(is_pinned=desired).update(is_pinned=desired)
        if changed:
            audit(request, row, action="content_pinned" if desired else "content_unpinned",
                  note="置顶碎碎念" if desired else "取消置顶碎碎念")
    return json_ok({"pinned": desired})


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


def comment_payload(row, authors, username, blocked=(), mentions=None):
    parent = row.reply_to
    reply_to = None
    if parent:
        reply_to = {"id": parent.pk, "unavailable": parent.is_deleted or parent.author_username in blocked}
        if not reply_to["unavailable"]:
            reply_to.update({"author": authors[parent.author_username], "content": parent.content[:80] or "图片或表情包"})
    return {"id": row.pk, "content": row.content, "author": authors[row.author_username], "created_at": row.created_at,
            "mention_usernames": resolved_mentions(row.author_username, row.content) if mentions is None else sorted(mention_names(row.content) & mentions.get(row.author_username, set())),
            "is_ai_reply": bool(getattr(row, "is_ai_reply", False)),
            "images": images_payload(row), "reply_to": reply_to,
            "can_delete": row.author_username == username, "is_own": row.author_username == username}


@require_http_methods(["GET", "POST"])
@api_errors
def comments(request, post_id):
    username = actor(request)
    post = visible_posts(username).filter(pk=post_id).first()
    if not post:
        return json_error("这条碎碎念已不可见", status=404)
    if request.method == "GET":
        qs = post.comments.filter(is_deleted=False).annotate(is_ai_reply=Exists(AssistantReplyJob.objects.filter(
            result_comment_id=OuterRef("pk"), status="completed"))).select_related("reply_to").prefetch_related("attachments__image")
        blocked = set(MurmurBlock.objects.filter(username=username).values_list("blocked_username", flat=True)) if username else set()
        if blocked:
            qs = qs.exclude(author_username__in=blocked)
        after = cursor(request, "after")
        before = cursor(request, "before")
        target_id = cursor(request, "target")
        target = qs.filter(pk=target_id).first() if target_id else None
        # 打开评论区时直接给最新的一页：长评论区从最旧的 30 条开始翻到底，
        # 是打开慢、滑不到底的根源。更早的评论用 before 向上补页。
        latest = after is None and before is None and target is None
        next_cursor = older_cursor = None
        if latest:
            newest = list(qs.order_by("-pk").values_list("pk", flat=True)[:30])
            rows = list(qs.filter(pk__in=newest))
            more = bool(newest) and qs.filter(pk__lt=min(newest)).exists()
            older_cursor = rows[0].pk if rows and more else None
        else:
            if after:
                qs = qs.filter(pk__gt=after)
            elif before:
                qs = qs.filter(pk__lt=before)
            elif target is not None:
                # Start near the exact comment even when it is beyond the first page.
                nearby = list(qs.filter(pk__lte=target.pk).order_by("-pk").values_list("pk", flat=True)[:10])
                qs = qs.filter(pk__gte=min(nearby))
            rows = list(qs[:31])
            more = len(rows) > 30
            rows = rows[:30]
            if after is not None or target is not None:
                next_cursor = rows[-1].pk if rows and more else None
            else:
                older_cursor = rows[0].pk if rows and more else None
        authors = authors_payload([row.author_username for row in rows] + [row.reply_to.author_username for row in rows if row.reply_to], username)
        mentions = resolve_many([(row.author_username, row.content) for row in rows])
        return json_ok({"items": [comment_payload(row, authors, username, blocked, mentions) for row in rows],
                        "target_found": bool(target) if target_id else None,
                        "next_cursor": next_cursor, "older_cursor": older_cursor})
    if not username:
        return json_error("登录后就可以评论", status=401)
    body = read_json(request)
    content = text(body, "content", 500)
    ids = image_ids(body, username, 4)
    if not content and not ids:
        return json_error("写点什么，或发送一张图片、表情包吧")
    key = client_key(body)
    ai_job = None
    parent_id = body.get("reply_to")
    if parent_id is not None and (type(parent_id) is not int or parent_id <= 0):
        return json_error("回复对象无效，请重新选择评论")
    with transaction.atomic():
        # Lock the parent so deleting a post cannot leave a new visible comment.
        if not Murmur.objects.select_for_update().filter(pk=post_id, is_deleted=False).exists():
            return json_error("这条碎碎念已删除", status=404)
        parent = None
        if parent_id is not None:
            parent = MurmurComment.objects.select_for_update().filter(pk=parent_id, murmur_id=post_id, is_deleted=False).exclude(
                author_username__in=MurmurBlock.objects.filter(username=username).values("blocked_username")).first()
            if not parent:
                return json_error("要回复的评论不存在、已删除或已被屏蔽", status=404)
        existing = MurmurComment.objects.select_related("reply_to").filter(author_username=username, client_key=key).first()
        if existing:
            if (existing.is_deleted or existing.murmur_id != post_id or existing.content != content or existing.reply_to_id != parent_id
                    or list(existing.attachments.values_list("image_id", flat=True)) != ids):
                return json_error("这次评论已经处理过，请重新发送", status=409)
            row, created = existing, False
        else:
            since = (timezone.now() - timedelta(seconds=5)).isoformat()
            if MurmurComment.objects.filter(author_username=username, created_at__gte=since).exists():
                return json_error("评论得有点快，请稍等 5 秒", status=429)
            row = MurmurComment.objects.create(murmur=post, reply_to=parent, author_username=username, content=content, client_key=key)
            MurmurCommentImage.objects.bulk_create([
                MurmurCommentImage(comment=row, image_id=i, position=p) for p, i in enumerate(ids)
            ])
            created = True
            mentioned = mention_recipients(username, content)
            def notify_comment():
                send_mentions(post, username, content, mentioned, row.pk)
                send_comment_notifications(post, username, content, parent, {user.username for user in mentioned})
            transaction.on_commit(notify_comment)
            ai_job = enqueue_reply(post, row)
        count = post.comments.filter(is_deleted=False).count()
    authors = authors_payload([username] + ([parent.author_username] if parent else []), username)
    return json_ok({"item": comment_payload(row, authors, username),
                    "comment_count": count, "replayed": not created, "ai_reply_queued": bool(ai_job and ai_job.status in {"queued", "processing"})}, status=201 if created else 200)


@require_http_methods(["DELETE"])
def comment_detail(request, comment_id):
    username = actor(request)
    if not username:
        return json_error("请先登录", status=401)
    with transaction.atomic():
        row = MurmurComment.objects.select_for_update().filter(pk=comment_id, murmur__is_deleted=False).first()
        if not row:
            return json_error("评论不存在", status=404)
        if row.author_username != username:
            return json_error("管理员下线内容请通过举报审核", status=403)
        if not row.is_deleted:
            row.is_deleted = True
            row.deleted_at = timestamp()
            row.deleted_by = username
            row.deletion_reason = "作者删除"
            row.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason"])
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
    if (comment.author_username if comment else post.author_username) == username:
        return json_error("不能举报自己的内容")
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
def pending_count(request):
    reports = MurmurReport.objects.filter(status="pending").count()
    appeals = MurmurAppeal.objects.filter(status="pending").count()
    return json_ok({"reports": reports, "appeals": appeals, "total": reports + appeals})


@require_admin(level=2)
@require_GET
@api_errors
def admin_reports(request):
    status = request.GET.get("status", "pending")
    if status not in {"pending", "resolved", "rejected", "all"}:
        return json_error("举报状态无效")
    qs = MurmurReport.objects.select_related("murmur", "comment").prefetch_related(
        "murmur__attachments__image", "murmur__videos", "comment__attachments__image").order_by("-id")
    if status != "all":
        qs = qs.filter(status=status)
    before = cursor(request)
    if before:
        qs = qs.filter(pk__lt=before)
    rows = list(qs[:31])
    more = len(rows) > 30
    rows = rows[:30]
    keys = [target_key("comment", row.comment_id) if row.comment_id else target_key("post", row.murmur_id) for row in rows]
    appeals = {appeal.target_key: appeal for appeal in MurmurAppeal.objects.filter(target_key__in=keys)}
    items = []
    for row, key in zip(rows, keys):
        target = row.comment or row.murmur
        appeal = appeals.get(key)
        items.append({"id": row.pk, "post_id": row.murmur_id, "comment_id": row.comment_id,
            "content": target.content, "author_username": target.author_username,
            "images": images_payload(target), "videos": videos_payload(target),
            "reporter_username": row.reporter_username, "reason": row.reason, "details": row.details, "status": row.status,
            "created_at": row.created_at, "reviewer_username": row.reviewer_username, "review_note": row.review_note,
            "reviewed_at": row.reviewed_at, "removed": target.is_deleted or row.murmur.is_deleted,
            "appeal_status": appeal.status if appeal else "", "appeal_deadline": target.appeal_deadline,
            "deleted_at": target.deleted_at, "deleted_by": target.deleted_by,
            "deletion_reason": target.deletion_reason, "restored_at": target.restored_at})
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
    reviewer = request.kflow_admin["username"]
    target = None
    removed_now = False
    with transaction.atomic():
        row = MurmurReport.objects.select_for_update().select_related("murmur", "comment").filter(pk=report_id).first()
        if not row:
            return json_error("举报不存在", status=404)
        if row.status != "pending":
            return json_ok({"status": row.status, "replayed": True})
        if remove:
            target = row.comment or row.murmur
            if not target.is_deleted:
                mark_deleted(target, reviewer, note or "举报核实后下线")
                audit(request, target, comment=bool(row.comment_id), note=note or "举报处理下线")
                removed_now = True
        row.status = decision
        row.reviewer_username = reviewer
        row.review_note = note
        row.reviewed_at = timestamp()
        row.save(update_fields=["status", "reviewer_username", "review_note", "reviewed_at"])
    if removed_now:
        notify_removal(target, comment=bool(row.comment_id), reviewer=reviewer)
    notify_report_result(row.reporter_username, decision, remove, note, row.murmur_id,
                         target.appeal_deadline if removed_now else "")
    return json_ok({"status": decision, "removed": remove,
                    "appeal_deadline": target.appeal_deadline if removed_now else ""})


@require_GET
@api_errors
def appeal_context(request):
    username = actor(request)
    if not username:
        return json_error("请先登录", status=401)
    kind, ident = parse_target(request.GET.get("target", ""))
    target = (MurmurComment.objects.select_related("murmur").filter(pk=ident).first()
              if kind == "comment" else Murmur.objects.filter(pk=ident).first())
    if not target:
        return json_error("内容不存在", status=404)
    if target.author_username != username:
        return json_error("只能查看自己的申诉", status=403)
    key = target_key(kind, target.pk)
    existing = MurmurAppeal.objects.filter(target_key=key).first()
    deleted_by_self = target.deleted_by == username
    if not target.is_deleted:
        can_appeal, message = False, "内容当前可见，无需申诉"
    elif deleted_by_self:
        can_appeal, message = False, "自行删除的内容不支持申诉"
    elif existing:
        can_appeal = False
        message = {"pending": "申诉已提交，等待管理员复核", "accepted": "申诉已通过，内容已恢复",
                   "rejected": "申诉未通过，维持删除"}.get(existing.status, "")
    elif not appeal_window_open(target.appeal_deadline):
        can_appeal, message = False, "申诉期已结束"
    else:
        can_appeal, message = True, ""
    authors = authors_payload([target.author_username])
    return json_ok({
        "target": key,
        "type": kind,
        "post_id": target.pk if kind == "post" else target.murmur_id,
        "comment_id": target.pk if kind == "comment" else None,
        "content": target.content,
        "images": images_payload(target),
        "videos": videos_payload(target),
        "author": authors[target.author_username],
        "created_at": target.created_at,
        "deleted_at": target.deleted_at,
        "deletion_reason": target.deletion_reason,
        "appeal_deadline": target.appeal_deadline,
        "can_appeal": can_appeal,
        "message": message,
        "appeal": appeal_payload(existing) if existing else None,
    })


@require_POST
@api_errors
def submit_appeal(request):
    username = actor(request)
    if not username:
        return json_error("请先登录", status=401)
    body = read_json(request)
    kind, ident = parse_target(body.get("target", ""))
    reason = text(body, "reason", 1000)
    if not reason:
        raise InputError("请填写申诉理由")
    key = target_key(kind, ident)
    with transaction.atomic():
        target = (MurmurComment.objects.select_for_update().filter(pk=ident).first()
                  if kind == "comment" else Murmur.objects.select_for_update().filter(pk=ident).first())
        if not target:
            return json_error("内容不存在", status=404)
        if target.author_username != username:
            return json_error("只能申诉自己的内容", status=403)
        if not target.is_deleted:
            return json_error("内容未被删除，无需申诉")
        if target.deleted_by == username:
            return json_error("自行删除的内容不支持申诉")
        if not appeal_window_open(target.appeal_deadline):
            return json_error("申诉期已结束")
        if MurmurAppeal.objects.filter(target_key=key).exists():
            return json_error("该内容已经申诉过", status=409)
        try:
            with transaction.atomic():
                appeal = MurmurAppeal.objects.create(
                    murmur_id=target.pk if kind == "post" else target.murmur_id,
                    comment_id=target.pk if kind == "comment" else None,
                    target_key=key,
                    appellant_username=username,
                    reason=reason,
                )
        except IntegrityError:
            return json_error("该内容已经申诉过", status=409)
    notify_user(username, "申诉已提交",
                f"你的申诉已进入复核队列，可在 {deadline_label(target.appeal_deadline)} 前等待管理员处理。",
                f"/murmurs?appeal={key}")
    return json_ok({"appeal": appeal_payload(appeal)}, status=201)


@require_admin(level=2)
@require_GET
@api_errors
def admin_appeals(request):
    status = request.GET.get("status", "pending")
    if status not in {"pending", "accepted", "rejected", "all"}:
        return json_error("申诉状态无效")
    qs = MurmurAppeal.objects.select_related("murmur", "comment").prefetch_related(
        "murmur__attachments__image", "murmur__videos", "comment__attachments__image").order_by("-id")
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
        items.append({
            "id": row.pk, "target": row.target_key,
            "target_type": "comment" if row.comment_id else "post",
            "post_id": row.murmur_id, "comment_id": row.comment_id,
            "content": target.content, "author_username": target.author_username,
            "images": images_payload(target), "videos": videos_payload(target),
            "appellant_username": row.appellant_username, "reason": row.reason, "status": row.status,
            "created_at": row.created_at, "reviewer_username": row.reviewer_username,
            "review_note": row.review_note, "reviewed_at": row.reviewed_at,
            "deleted_by": target.deleted_by, "deletion_reason": target.deletion_reason,
            "deleted_at": target.deleted_at, "appeal_deadline": target.appeal_deadline,
            "removed": target.is_deleted,
        })
    return json_ok({"items": items, "next_cursor": rows[-1].pk if rows and more else None})


@require_admin(level=2)
@require_POST
@api_errors
def review_appeal(request, appeal_id):
    body = read_json(request)
    decision = text(body, "decision", 16)
    note = text(body, "note", 500)
    if decision not in {"accepted", "rejected"}:
        return json_error("处理方式无效")
    reviewer = request.kflow_admin["username"]
    with transaction.atomic():
        row = MurmurAppeal.objects.select_for_update().select_related("murmur", "comment").filter(pk=appeal_id).first()
        if not row:
            return json_error("申诉不存在", status=404)
        if row.status != "pending":
            return json_ok({"status": row.status, "replayed": True})
        target = (MurmurComment.objects.select_for_update().filter(pk=row.comment_id).first()
                  if row.comment_id else Murmur.objects.select_for_update().filter(pk=row.murmur_id).first())
        if not target:
            return json_error("内容不存在", status=404)
        if decision == "accepted" and target.is_deleted:
            target.is_deleted = False
            target.restored_at = timestamp()
            target.save(update_fields=["is_deleted", "restored_at"])
            audit(request, target, comment=bool(row.comment_id), note=note or "申诉复核恢复", action="content_restored")
        elif decision == "rejected":
            audit(request, target, comment=bool(row.comment_id), note=note or "申诉复核维持删除", action="appeal_rejected")
        row.status = decision
        row.reviewer_username = reviewer
        row.review_note = note
        row.reviewed_at = timestamp()
        row.save(update_fields=["status", "reviewer_username", "review_note", "reviewed_at"])
    link = f"/murmurs?post={row.murmur_id}"
    if decision == "accepted":
        notify_user(target.author_username, "申诉通过，内容已恢复",
                    note or "管理员复核后恢复了你的内容。", link, actor_username=reviewer)
        reporters = set(MurmurReport.objects.filter(murmur_id=row.murmur_id, comment_id=row.comment_id)
                        .values_list("reporter_username", flat=True))
        for reporter in reporters:
            notify_user(reporter, "举报内容经复核恢复", "你举报的内容经申诉复核后已恢复显示。", link, actor_username=reviewer)
    else:
        notify_user(target.author_username, "申诉未通过，维持删除",
                    note or "管理员复核后维持删除处理。", f"/murmurs?appeal={row.target_key}", actor_username=reviewer)
    return json_ok({"status": decision, "restored": decision == "accepted"})
