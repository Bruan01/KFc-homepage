# pyright: reportMissingImports=false
"""Forum API views."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from django.db import transaction
from django.db.models import Count, F, Q
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import get_admin_context
from apps.core.responses import json_error, json_ok
from apps.accounts.models import User

from .models import ForumCategory, ForumLike, ForumReply, ForumTopic


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_actor(request) -> tuple[str, str]:
    """Return (username, role) for the current request, or ('', 'guest')."""
    admin = get_admin_context(request)
    if admin:
        return admin["username"], "admin"
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user.username, "user"
    return "", "guest"


def _initials(username: str) -> str:
    parts = username.strip().split()
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()[:2]


def _category_payload(cat: ForumCategory) -> dict:
    return {
        "id": cat.pk,
        "slug": cat.slug,
        "name": cat.name,
        "icon": cat.icon,
        "color": cat.color,
    }


def _profile_payload(user: User, *, include_private: bool = False) -> dict:
    display_name = (user.display_name or "").strip() or user.username
    payload = {
        "username": user.username,
        "display_name": display_name,
        "avatar_url": user.avatar_url or "",
        "bio": user.bio or "",
        "created_at": user.created_at,
        "initials": _initials(display_name),
        "topic_count": ForumTopic.objects.filter(
            author_username=user.username,
            status=ForumTopic.STATUS_OPEN,
        ).count(),
        "reply_count": ForumReply.objects.filter(
            author_username=user.username,
            is_deleted=False,
            topic__status=ForumTopic.STATUS_OPEN,
        ).count(),
    }
    if include_private:
        payload["email"] = user.email or ""
    return payload


def _author_payload(username: str) -> dict:
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return {
            "username": username,
            "display_name": username,
            "avatar_url": "",
            "initials": _initials(username),
        }
    display_name = (user.display_name or "").strip() or user.username
    return {
        "username": user.username,
        "display_name": display_name,
        "avatar_url": user.avatar_url or "",
        "initials": _initials(display_name),
    }


def _valid_avatar_url(value: str) -> bool:
    if not value:
        return True
    parsed = urlparse(value)
    return (parsed.scheme == "https" and bool(parsed.netloc)) or (
        value.startswith("/") and not value.startswith("//")
    )


def _profile_topic_payload(topic: ForumTopic) -> dict:
    return {
        "id": topic.pk,
        "title": topic.title,
        "excerpt": topic.content[:160] + ("…" if len(topic.content) > 160 else ""),
        "category": topic.category.name,
        "category_slug": topic.category.slug,
        "created_at": topic.created_at.isoformat(),
        "replies": topic.replies.filter(is_deleted=False).count(),
        "views": topic.views,
    }


def _profile_reply_payload(reply: ForumReply) -> dict:
    return {
        "id": reply.pk,
        "topic_id": reply.topic_id,
        "topic_title": reply.topic.title,
        "topic_author": reply.topic.author_username,
        "content": reply.content[:200] + ("…" if len(reply.content) > 200 else ""),
        "created_at": reply.created_at.isoformat(),
    }


def _topic_payload(
    topic: ForumTopic,
    *,
    liked_by: str = "",
    like_count: int | None = None,
    reply_count: int | None = None,
) -> dict:
    if like_count is None:
        like_count = topic.likes.count()
    if reply_count is None:
        reply_count = topic.reply_count
    liked = False
    if liked_by:
        liked = topic.likes.filter(username=liked_by).exists()
    body = {
        "id": topic.pk,
        "title": topic.title,
        "excerpt": topic.content[:120] + ("…" if len(topic.content) > 120 else ""),
        "content": topic.content,
        "author": topic.author_username,
        "author_profile": _author_payload(topic.author_username),
        "initials": _initials(topic.author_username),
        "category": topic.category.name,
        "category_slug": topic.category.slug,
        "category_color": topic.category.color,
        "tags": topic.tag_list,
        "replies": reply_count,
        "views": topic.views,
        "likes": like_count,
        "liked": liked,
        "pinned": topic.is_pinned,
        "featured": topic.is_featured,
        "status": topic.status,
        "created_at": topic.created_at.isoformat(),
        "updated_at": topic.updated_at.isoformat(),
        "active": _relative_time(topic.updated_at),
    }
    return body


def _reply_payload(reply: ForumReply) -> dict:
    return {
        "id": reply.pk,
        "topic_id": reply.topic_id,
        "author": reply.author_username,
        "author_profile": _author_payload(reply.author_username),
        "initials": _initials(reply.author_username),
        "content": reply.content,
        "created_at": reply.created_at.isoformat(),
        "updated_at": reply.updated_at.isoformat(),
    }


def _relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = int((now - dt).total_seconds())  # pi-lens-ignore: unchecked-throwing-call-python
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{diff // 60} 分钟前"
    if diff < 86400:
        return f"{diff // 3600} 小时前"
    if diff < 86400 * 30:
        return f"{diff // 86400} 天前"
    return dt.strftime("%Y-%m-%d")


# ── user profiles ────────────────────────────────────────────────────────────


def _profile_response(user: User, *, is_self: bool = False):
    profile = _profile_payload(user, include_private=is_self)
    topics = list(
        ForumTopic.objects.filter(
            author_username=user.username,
            status=ForumTopic.STATUS_OPEN,
        )
        .select_related("category")
        .order_by("-created_at")[:20]
    )
    replies = list(
        ForumReply.objects.filter(
            author_username=user.username,
            is_deleted=False,
            topic__status=ForumTopic.STATUS_OPEN,
        )
        .select_related("topic")
        .order_by("-created_at")[:20]
    )
    profile["topics"] = [_profile_topic_payload(topic) for topic in topics]
    profile["replies"] = [_profile_reply_payload(reply) for reply in replies]
    return json_ok({"profile": profile})


@require_GET
def user_profile(request, username: str):
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return json_error("用户不存在", status=404)
    actor, _ = _get_actor(request)
    return _profile_response(user, is_self=actor == user.username)


@require_GET
def my_profile(request):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录", status=401)
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return json_error("用户不存在", status=404)
    return _profile_response(user, is_self=True)


@require_http_methods(["PATCH", "POST"])
def update_my_profile(request):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录", status=401)
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")

    display_name = str(body.get("display_name", body.get("displayName", ""))).strip()
    avatar_url = str(body.get("avatar_url", body.get("avatarUrl", ""))).strip()
    bio = str(body.get("bio", "")).strip()
    if len(display_name) > 100:
        return json_error("昵称最多 100 个字符")
    if len(avatar_url) > 500 or not _valid_avatar_url(avatar_url):
        return json_error("头像地址必须是 HTTPS 地址或本站路径")
    if len(bio) > 1000:
        return json_error("个人简介最多 1000 个字符")

    user = User.objects.get(username=username)
    user.display_name = display_name
    user.avatar_url = avatar_url
    user.bio = bio
    user.save(update_fields=["display_name", "avatar_url", "bio"])
    return _profile_response(user, is_self=True)


# ── category views ────────────────────────────────────────────────────────────

@require_GET
def categories(request):
    cats = ForumCategory.objects.filter(is_active=True)
    topic_counts = {
        row["category_id"]: row["cnt"]
        for row in ForumTopic.objects.filter(status=ForumTopic.STATUS_OPEN)
        .values("category_id")
        .annotate(cnt=Count("id"))
    }
    data = []
    for cat in cats:
        payload = _category_payload(cat)
        payload["topic_count"] = topic_counts.get(cat.pk, 0)
        data.append(payload)
    return json_ok({"categories": data})


# ── topic list & detail ───────────────────────────────────────────────────────

@require_GET
def topics(request):
    username, _ = _get_actor(request)

    qs = ForumTopic.objects.filter(status=ForumTopic.STATUS_OPEN).select_related("category")

    # filters
    cat_slug = request.GET.get("category", "").strip()
    if cat_slug and cat_slug != "all":
        qs = qs.filter(category__slug=cat_slug)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(content__icontains=q) | Q(tags__icontains=q) | Q(author_username__icontains=q))

    view = request.GET.get("view", "latest")  # latest | hot | featured
    if view == "featured":
        qs = qs.filter(is_featured=True)
    elif view == "hot":
        qs = qs.order_by("-views", "-created_at")
    else:
        qs = qs.order_by("-is_pinned", "-created_at")

    # pagination
    try:
        page = max(1, int(request.GET.get("page", 1)))
        page_size = min(50, max(1, int(request.GET.get("page_size", 20))))
    except ValueError:
        page, page_size = 1, 20
    total = qs.count()
    offset = (page - 1) * page_size
    topic_list = list(qs[offset: offset + page_size])

    # batch fetch like counts to avoid N+1
    topic_ids = [t.pk for t in topic_list]
    like_counts = {
        row["topic_id"]: row["cnt"]
        for row in ForumLike.objects.filter(topic_id__in=topic_ids)
        .values("topic_id").annotate(cnt=Count("id"))
    }
    liked_set: set[int] = set()
    if username:
        liked_set = set(
            ForumLike.objects.filter(topic_id__in=topic_ids, username=username)
            .values_list("topic_id", flat=True)
        )
    # Fetch reply counts in one query to avoid per-card count queries.
    reply_counts = {
        row["topic_id"]: row["cnt"]
        for row in ForumReply.objects.filter(topic_id__in=topic_ids, is_deleted=False)
        .values("topic_id").annotate(cnt=Count("id"))
    }

    items = []
    for t in topic_list:
        p = _topic_payload(
            t,
            like_count=like_counts.get(t.pk, 0),
            reply_count=reply_counts.get(t.pk, 0),
        )
        p["liked"] = t.pk in liked_set
        items.append(p)

    return json_ok({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": offset + page_size < total,
    })


@require_GET
def topic_detail(request, topic_id: int):
    username, _ = _get_actor(request)
    try:
        topic = ForumTopic.objects.select_related("category").get(pk=topic_id, status__in=[ForumTopic.STATUS_OPEN, ForumTopic.STATUS_CLOSED])
    except ForumTopic.DoesNotExist:
        return json_error("not found", status=404)

    # Increment atomically so simultaneous detail requests cannot overwrite one another.
    ForumTopic.objects.filter(pk=topic_id).update(views=F("views") + 1)
    topic.refresh_from_db(fields=["views", "updated_at"])

    replies = list(topic.replies.filter(is_deleted=False))
    payload = _topic_payload(topic, liked_by=username)
    payload["replies_detail"] = [_reply_payload(r) for r in replies]
    return json_ok({"topic": payload})


# ── create topic ──────────────────────────────────────────────────────────────

@require_POST
def create_topic(request):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录后再发帖", status=401)

    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")

    title = str(body.get("title", "")).strip()
    content = str(body.get("content", "")).strip()
    category_slug = str(body.get("category", "")).strip()
    tags_raw = str(body.get("tags", "")).strip()

    if not title:
        return json_error("标题不能为空")
    if len(title) > 256:
        return json_error("标题最多 256 个字符")
    if not content:
        return json_error("内容不能为空")
    if len(content) > 20000:
        return json_error("内容最多 20000 个字符")

    try:
        category = ForumCategory.objects.get(slug=category_slug, is_active=True)
    except ForumCategory.DoesNotExist:
        return json_error("分类不存在")

    # sanitize tags: comma-separated, up to 5, each ≤ 16 chars
    tags = ",".join(t[:16] for t in [x.strip() for x in tags_raw.split(",") if x.strip()][:5])

    with transaction.atomic():
        topic = ForumTopic.objects.create(
            category=category,
            title=title,
            content=content,
            author_username=username,
            tags=tags,
        )

    return json_ok({"topic": _topic_payload(topic)}, status=201)


# ── create reply ──────────────────────────────────────────────────────────────

@require_POST
def create_reply(request, topic_id: int):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录后再回复", status=401)

    try:
        topic = ForumTopic.objects.get(pk=topic_id, status=ForumTopic.STATUS_OPEN)
    except ForumTopic.DoesNotExist:
        return json_error("话题不存在或已关闭", status=404)

    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")

    content = str(body.get("content", "")).strip()
    if not content:
        return json_error("回复内容不能为空")
    if len(content) > 10000:
        return json_error("回复最多 10000 个字符")

    with transaction.atomic():
        reply = ForumReply.objects.create(
            topic=topic,
            author_username=username,
            content=content,
        )
        # touch topic.updated_at so it bubbles up in "latest" sort
        ForumTopic.objects.filter(pk=topic_id).update(updated_at=reply.created_at)

    return json_ok({"reply": _reply_payload(reply)}, status=201)


# ── like / unlike ─────────────────────────────────────────────────────────────

@require_http_methods(["POST", "DELETE"])
def like_topic(request, topic_id: int):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录", status=401)

    try:
        topic = ForumTopic.objects.get(pk=topic_id, status=ForumTopic.STATUS_OPEN)
    except ForumTopic.DoesNotExist:
        return json_error("话题不存在", status=404)

    if request.method == "POST":
        ForumLike.objects.get_or_create(topic=topic, username=username)
    else:
        ForumLike.objects.filter(topic=topic, username=username).delete()

    like_count = ForumLike.objects.filter(topic=topic).count()
    liked = ForumLike.objects.filter(topic=topic, username=username).exists()
    return json_ok({"likes": like_count, "liked": liked})


# ── stats ─────────────────────────────────────────────────────────────────────

@require_GET
def stats(request):
    total_topics = ForumTopic.objects.filter(status=ForumTopic.STATUS_OPEN).count()
    total_replies = ForumReply.objects.filter(is_deleted=False).count()
    from apps.accounts.models import User
    total_members = User.objects.count()
    return json_ok({
        "topics": total_topics,
        "replies": total_replies,
        "members": total_members,
    })
