# pyright: reportMissingImports=false
"""Forum API views."""
from __future__ import annotations

import io
import json
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import FileResponse, HttpResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import get_admin_context
from apps.core.responses import json_error, json_ok
from apps.accounts.models import User
from apps.points.services import (
    PointsError,
    account_payload as points_account_payload,
    award_like_received,
    award_reply_created,
    award_topic_created,
)

from .models import ForumCategory, ForumImage, ForumLike, ForumReply, ForumReplyLike, ForumTopic, ForumTopicLink
from apps.gamification.services import badges_payload, check_user_achievements, promote_user_level, compute_user_stats
from apps.notifications.services import notify as notify_user


def _check_badges(user):
    """行为后即时检查勋章；任何失败不影响主流程。"""
    try:
        return check_user_achievements(user)
    except Exception:
        return []
from .services import get_boost_tiers, parse_image_ids, purchase_boost, record_dedup_view

MAX_TOPIC_IMAGES = 9
MAX_TOPIC_LINKS = 3
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}
IMAGE_MAX_DIMENSION = 1600


def _classify_link(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host in {"github.com"} or host.endswith(".github.com"):
        return ForumTopicLink.TYPE_GITHUB
    if host in {"gitee.com"} or host.endswith(".gitee.com"):
        return ForumTopicLink.TYPE_GITEE
    return ForumTopicLink.TYPE_LIVE


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
    try:
        payload["points"] = points_account_payload(user)
    except Exception:
        payload["points"] = None
    if include_private:
        payload["email"] = user.email or ""
    return payload


def _author_payload(username: str, showcase: dict | None = None) -> dict:
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return {
            "username": username,
            "display_name": username,
            "avatar_url": "",
            "initials": _initials(username),
            "showcase": showcase,
        }
    level = 0
    try:
        from apps.points.models import PointAccount
        level = int(PointAccount.objects.filter(username=username).values_list("reputation_level", flat=True).first() or 0)
    except Exception:
        level = 0
    display_name = (user.display_name or "").strip() or user.username
    return {
        "username": user.username,
        "display_name": display_name,
        "avatar_url": user.avatar_url or "",
        "initials": _initials(display_name),
        "level": level,
        "showcase": showcase,
    }


def _showcase_map(usernames: list[str]) -> dict:
    """批量取作者佩戴中的勋章，避免列表页 N+1。"""
    from apps.gamification.models import UserStats

    result = {}
    for stats in UserStats.objects.filter(user__username__in=set(usernames)).select_related("showcase"):
        if stats.showcase:
            result[stats.user.username] = {
                "code": stats.showcase.code,
                "name": stats.showcase.name,
                "icon": stats.showcase.icon,
                "tier": stats.showcase.tier,
            }
    return result


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


def _link_payload(link: ForumTopicLink) -> dict:
    return {
        "id": link.pk,
        "url": link.url,
        "type": link.link_type,
        "name": link.display_name or link.url,
    }


def _links_for_topics(topic_ids: list[int]) -> dict[int, list[dict]]:
    links: dict[int, list[dict]] = {}
    for link in ForumTopicLink.objects.filter(topic_id__in=topic_ids):
        links.setdefault(link.topic_id, []).append(_link_payload(link))
    return links


def _images_payload(topic: ForumTopic) -> list[dict]:
    ids = parse_image_ids(topic.images)
    if not ids:
        return []
    rows = ForumImage.objects.filter(id__in=ids)
    by_id = {row.pk: row for row in rows}
    result = []
    for image_id in ids:
        row = by_id.get(image_id)
        if row:
            result.append({"id": row.pk, "url": f"/api/forum/images/{row.pk}"})
    return result


def _boosted_flag(topics: list[ForumTopic]) -> set[int]:
    from django.utils import timezone

    from .models import TopicBoost

    now = timezone.now()
    active = TopicBoost.objects.filter(
        status=TopicBoost.STATUS_ACTIVE, ends_at__gt=now, topic_id__in=[t.pk for t in topics]
    ).values_list("topic_id", flat=True)
    return set(active)


def _topic_payload(
    topic: ForumTopic,
    *,
    liked_by: str = "",
    like_count: int | None = None,
    reply_count: int | None = None,
    author_showcase: dict | None = None,
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
        "author_profile": _author_payload(topic.author_username, author_showcase),
        "initials": _initials(topic.author_username),
        "category": topic.category.name,
        "category_slug": topic.category.slug,
        "category_color": topic.category.color,
        "tags": topic.tag_list,
        "links": [_link_payload(link) for link in topic.links.all()],
        "images": _images_payload(topic),
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


def _reply_payload(reply: ForumReply, *, liked_by: str = "", like_count: int | None = None) -> dict:
    if like_count is None:
        like_count = reply.likes.count()
    liked = False
    if liked_by:
        liked = reply.likes.filter(username=liked_by).exists()
    return {
        "id": reply.pk,
        "topic_id": reply.topic_id,
        "author": reply.author_username,
        "author_profile": _author_payload(reply.author_username),
        "initials": _initials(reply.author_username),
        "content": reply.content,
        "likes": like_count,
        "liked": liked,
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
    try:
        profile["badges"] = badges_payload(user)
        profile["level"] = int((points_account_payload(user) or {}).get("reputationLevel", 0))
    except Exception:
        profile["badges"] = []
        profile["level"] = 0
    try:
        from apps.gamification.services import showcase_payload

        profile["showcase"] = showcase_payload(user)
    except Exception:
        profile["showcase"] = None
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

    view = request.GET.get("view", "latest")  # latest | hot | featured | boosted
    if view == "featured":
        qs = qs.filter(is_featured=True)
    elif view == "hot":
        qs = qs.order_by("-hot_score", "-created_at")
    elif view == "boosted":
        from django.utils import timezone

        from .models import TopicBoost

        now = timezone.now()
        boosted_ids = set(
            TopicBoost.objects.filter(status=TopicBoost.STATUS_ACTIVE, ends_at__gt=now)
            .values_list("topic_id", flat=True)
        )
        qs = qs.filter(id__in=boosted_ids).order_by("-hot_score", "-created_at")
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
    links_map = _links_for_topics(topic_ids)
    boosted_ids = _boosted_flag(topic_list)

    showcase_map = _showcase_map({t.author_username for t in topic_list})
    items = []
    for t in topic_list:
        p = _topic_payload(
            t,
            like_count=like_counts.get(t.pk, 0),
            reply_count=reply_counts.get(t.pk, 0),
            author_showcase=showcase_map.get(t.author_username),
        )
        p["liked"] = t.pk in liked_set
        p["links"] = links_map.get(t.pk, [])
        p["boosted"] = t.pk in boosted_ids
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

    # Dedup counter: one per viewer (username or anon cookie) per day.
    viewer_key = username or request.COOKIES.get("kflow_viewer", "") or _anon_viewer_key(request)
    try:
        record_dedup_view(topic, viewer_key)
    except Exception:
        pass

    topic.refresh_from_db(fields=["views", "updated_at"])
    replies = list(topic.replies.filter(is_deleted=False))
    reply_ids = [r.pk for r in replies]
    reply_like_counts = {
        row["reply_id"]: row["cnt"]
        for row in ForumReplyLike.objects.filter(reply_id__in=reply_ids)
        .values("reply_id").annotate(cnt=Count("id"))
    }
    liked_reply_ids: set[int] = set()
    if username:
        liked_reply_ids = set(
            ForumReplyLike.objects.filter(reply_id__in=reply_ids, username=username)
            .values_list("reply_id", flat=True)
        )
    payload = _topic_payload(topic, liked_by=username, author_showcase=_showcase_map([topic.author_username]).get(topic.author_username))
    payload["boosted"] = bool(topic.active_boost())
    payload["replies_detail"] = [
        _reply_payload(r, liked_by=username, like_count=reply_like_counts.get(r.pk, 0))
        for r in replies
    ]
    data = json_ok({"topic": payload})
    response = HttpResponse(data.content, content_type="application/json; charset=utf-8")
    if not username and viewer_key:
        response.set_cookie("kflow_viewer", viewer_key, max_age=365 * 86400, samesite="Lax", httponly=True)
    return response


def _anon_viewer_key(request) -> str:
    existing = request.COOKIES.get("kflow_viewer", "")
    if existing:
        return existing
    return f"anon-{secrets.token_hex(8)}"


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

    # images: up to 9 ids owned by the uploader
    raw_images = body.get("images", [])
    if not isinstance(raw_images, list):
        raw_images = []
    image_ids: list[int] = []
    for item in raw_images[:MAX_TOPIC_IMAGES]:
        try:
            image_ids.append(int(item))
        except (TypeError, ValueError):
            continue
    valid_images = list(
        ForumImage.objects.filter(id__in=image_ids, uploader_username=username).values_list("id", flat=True)
    )
    image_ids = [i for i in image_ids if i in valid_images][:MAX_TOPIC_IMAGES]

    # links: up to 3, http(s) only, typed by host
    raw_links = body.get("links", [])
    if not isinstance(raw_links, list):
        raw_links = []
    seen_urls: set[str] = set()
    clean_links: list[dict] = []
    for item in raw_links[:MAX_TOPIC_LINKS]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            return json_error("项目链接必须是 http/https 地址")
        if len(url) > 500:
            return json_error("项目链接过长")
        if urlparse(url).hostname is None:
            return json_error("项目链接格式不正确")
        display = str(item.get("name", "")).strip()[:120]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        clean_links.append({"url": url, "name": display})

    with transaction.atomic():
        topic = ForumTopic.objects.create(
            category=category,
            title=title,
            content=content,
            author_username=username,
            tags=tags,
            images=json.dumps(image_ids),
        )
        for order, link in enumerate(clean_links):
            ForumTopicLink.objects.create(
                topic=topic,
                url=link["url"],
                link_type=_classify_link(link["url"]),
                display_name=link["name"],
                sort_order=order,
            )

    # award points (outside topic transaction; idempotent per topic)
    new_badges: list = []
    user_obj = User.objects.filter(username=username).first()
    if user_obj is not None:
        try:
            award_topic_created(user_obj, topic.pk)
        except PointsError:
            pass
        new_badges = _check_badges(user_obj)
    badge_note = f"，并获得勋章「{new_badges[0].name}」" if new_badges else ""

    return json_ok({
        "topic": _topic_payload(topic),
        "newBadges": [{"name": b.name, "icon": b.icon, "tier": b.tier} for b in new_badges],
        "badgeNote": badge_note,
    }, status=201)


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

    # award points to the commenter (idempotent per reply)
    new_badges: list = []
    user_obj = User.objects.filter(username=username).first()
    if user_obj is not None:
        try:
            award_reply_created(user_obj, reply.pk)
        except PointsError:
            pass
        new_badges = _check_badges(user_obj)
    if topic.author_username != username:
        try:
            topic_author = User.objects.get(username=topic.author_username)
            notify_user(
                recipient=topic_author, type_="reply",
                title="你的作品收到 1 条新评论",
                body=f"{username} 评论了「{topic.title[:40]}」",
                link=f"/forum?topic={topic.pk}", actor_username=username,
            )
        except User.DoesNotExist:
            pass
    return json_ok({
        "reply": _reply_payload(reply),
        "newBadges": [{"name": b.name, "icon": b.icon, "tier": b.tier} for b in new_badges],
    }, status=201)


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
        _, created = ForumLike.objects.get_or_create(topic=topic, username=username)
        if created:
            try:
                author = User.objects.get(username=topic.author_username)
                award_like_received(author, liker_username=username, kind="topic", object_id=topic.pk)
                notify_user(
                    recipient=author, type_="like",
                    title="你的作品收到 1 个新点赞",
                    body=f"{username} 赞了「{topic.title[:40]}」",
                    link=f"/forum?topic={topic.pk}", actor_username=username,
                )
            except (User.DoesNotExist, PointsError):
                pass
    else:
        ForumLike.objects.filter(topic=topic, username=username).delete()

    try:
        actor_obj = User.objects.get(username=username)
        _check_badges(actor_obj)
    except User.DoesNotExist:
        pass
    try:
        author_obj = User.objects.get(username=topic.author_username)
        _check_badges(author_obj)
    except User.DoesNotExist:
        pass
    like_count = ForumLike.objects.filter(topic=topic).count()
    liked = ForumLike.objects.filter(topic=topic, username=username).exists()
    return json_ok({"likes": like_count, "liked": liked})


@require_http_methods(["POST", "DELETE"])
def like_reply(request, reply_id: int):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录", status=401)

    reply = ForumReply.objects.filter(pk=reply_id, is_deleted=False).select_related("topic").first()
    if not reply or reply.topic.status != ForumTopic.STATUS_OPEN:
        return json_error("回复不存在", status=404)

    if request.method == "POST":
        _, created = ForumReplyLike.objects.get_or_create(reply=reply, username=username)
        if created:
            try:
                author = User.objects.get(username=reply.author_username)
                award_like_received(author, liker_username=username, kind="reply", object_id=reply.pk)
                notify_user(
                    recipient=author, type_="reply_like",
                    title="你的评论收到 1 个新点赞",
                    body=f"{username} 在「{reply.topic.title[:36]}」中赞了你的评论",
                    link=f"/forum?topic={reply.topic_id}", actor_username=username,
                )
            except (User.DoesNotExist, PointsError):
                pass
    else:
        ForumReplyLike.objects.filter(reply=reply, username=username).delete()

    try:
        actor_obj = User.objects.get(username=username)
        _check_badges(actor_obj)
    except User.DoesNotExist:
        pass
    try:
        author_obj = User.objects.get(username=reply.author_username)
        _check_badges(author_obj)
    except User.DoesNotExist:
        pass
    like_count = ForumReplyLike.objects.filter(reply=reply).count()
    liked = ForumReplyLike.objects.filter(reply=reply, username=username).exists()
    return json_ok({"likes": like_count, "liked": liked})


# ── topic images ──────────────────────────────────────────────────────────────


@require_POST
def upload_image(request):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录后再上传图片", status=401)

    upload = request.FILES.get("file")
    if upload is None:
        return json_error("缺少 file 字段")
    if upload.size > IMAGE_MAX_BYTES:
        return json_error("图片最大 5MB", status=413)

    try:
        from PIL import Image

        image = Image.open(upload)
        image.verify()
        upload.seek(0)
        image = Image.open(upload)
        image.load()
    except Exception:
        return json_error("不支持的图片格式")

    fmt = (image.format or "").upper()
    if fmt not in IMAGE_ALLOWED_FORMATS:
        return json_error("仅支持 JPG / PNG / WEBP / GIF 图片")

    # downscale oversized images, keep GIF animation untouched
    if fmt != "GIF" and max(image.width, image.height) > IMAGE_MAX_DIMENSION:
        ratio = IMAGE_MAX_DIMENSION / max(image.width, image.height)
        image = image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))))

    buf = io.BytesIO()
    if fmt == "GIF":
        buf.write(upload.read())
        content_type = "image/gif"
    elif fmt == "PNG":
        image.save(buf, format="PNG", optimize=True)
        content_type = "image/png"
    elif fmt == "WEBP":
        image.save(buf, format="WEBP", quality=85)
        content_type = "image/webp"
    else:
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(buf, format="JPEG", quality=85)
        content_type = "image/jpeg"
    data = buf.getvalue()

    row = ForumImage(
        uploader_username=username,
        content_type=content_type,
        file_size=len(data),
        width=image.width,
        height=image.height,
    )
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[content_type]
    row.file.save(f"{username}-{int(datetime.now(timezone.utc).timestamp())}-{secrets.token_hex(4)}{ext}", io.BytesIO(data), save=True)
    return json_ok({"image": {"id": row.pk, "url": f"/api/forum/images/{row.pk}"}}, status=201)


@require_GET
def serve_image(request, image_id: int):
    row = ForumImage.objects.filter(pk=image_id).first()
    if not row:
        return json_error("图片不存在", status=404)
    try:
        handle = row.file.open("rb")
    except OSError:
        return json_error("图片文件丢失", status=404)
    response = FileResponse(handle, content_type=row.content_type or "application/octet-stream")
    response["Cache-Control"] = "public, max-age=86400"
    return response


# ── boosts ────────────────────────────────────────────────────────────────────


@require_GET
def boost_tiers(request):
    return json_ok({"tiers": get_boost_tiers(), "max_active": 3})


@require_POST
def boost_topic(request, topic_id: int):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录", status=401)
    try:
        topic = ForumTopic.objects.get(pk=topic_id)
    except ForumTopic.DoesNotExist:
        return json_error("话题不存在", status=404)
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")
    tier = str(body.get("tier", "")).strip()
    try:
        user_obj = User.objects.get(username=username)
    except User.DoesNotExist:
        return json_error("用户不存在", status=404)
    try:
        boost, info = purchase_boost(user=user_obj, topic=topic, tier=tier)
    except PointsError as exc:
        message = exc.message
        if message == "insufficient points":
            message = "积分不足：通过发帖、评论、被点赞赚取积分后再来加热"
        return json_error(message, status=exc.status)
    new_badges = _check_badges(user_obj)
    from apps.points.services import account_payload as _points_account_payload

    balance = _points_account_payload(user_obj)["balance"]
    return json_ok({
        "boost": info,
        "balance": balance,
        "newBadges": [{"name": b.name, "icon": b.icon, "tier": b.tier} for b in new_badges],
    }, status=201)


# ── OG share page ─────────────────────────────────────────────────────────────


@require_GET
def share_topic_page(request, topic_id: int):
    """Static-friendly share entry: OG meta + auto redirect to /forum?topic=<id>."""
    topic = (
        ForumTopic.objects.select_related("category")
        .filter(pk=topic_id, status=ForumTopic.STATUS_OPEN)
        .first()
    )
    if not topic:
        return json_error("话题不存在", status=404)
    base = request.build_absolute_uri("/").rstrip("/")
    share_url = f"{base}/t/{topic.pk}"
    image_ids = parse_image_ids(topic.images)
    og_image = f"{base}/api/forum/images/{image_ids[0]}" if image_ids else ""
    title_escaped = topic.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    desc_escaped = topic.content[:120].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title_escaped} | KFlow Vibecoding 社区</title>
<meta name="description" content="{desc_escaped}">
<meta property="og:title" content="{title_escaped}">
<meta property="og:description" content="{desc_escaped}">
<meta property="og:type" content="article">
<meta property="og:url" content="{share_url}">
{'<meta property="og:image" content="' + og_image + '">' if og_image else ''}
<meta http-equiv="refresh" content="0;url=/forum?topic={topic.pk}">
<script>location.replace("/forum?topic={topic.pk}");</script>
</head>
<body></body>
</html>"""
    return HttpResponse(html, content_type="text/html; charset=utf-8")


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
