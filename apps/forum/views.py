# pyright: reportMissingImports=false
"""Forum API views."""
from __future__ import annotations

import io
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.http import FileResponse, HttpResponse
from django.utils import timezone as django_timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import get_admin_context, require_admin
from apps.core.responses import json_error, json_ok
from apps.accounts.models import User
from apps.points.services import (
    PointsError,
    account_payload as points_account_payload,
    award_like_received,
    award_reply_created,
    award_topic_created,
)

from .models import (
    ForumCategory,
    ForumImage,
    ForumLike,
    ForumModerationAction,
    ForumReply,
    ForumReplyLike,
    ForumReport,
    ForumTopic,
    ForumTopicLink,
)
from apps.gamification.services import badges_payload, check_user_achievements, promote_user_level, compute_user_stats
from apps.notifications.services import notify as notify_user


def _check_badges(user):
    """行为后即时检查勋章；任何失败不影响主流程。"""
    try:
        return check_user_achievements(user)
    except Exception:
        logger.exception("论坛操作后的成就检查失败", extra={"username": getattr(user, "username", "")})
        return []
from .services import get_boost_tiers, parse_image_ids, purchase_boost, record_dedup_view

MAX_TOPIC_IMAGES = 9
MAX_TOPIC_LINKS = 3
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}
IMAGE_MAX_DIMENSION = 1600
REPLY_PAGE_SIZE_DEFAULT = 30
REPLY_PAGE_SIZE_MAX = 50
REPORT_REASONS = {"spam", "abuse", "copyright", "other"}
logger = logging.getLogger(__name__)


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


def _can_manage_forum_object(request, author_username: str, category_slug: str = "") -> tuple[str, str, bool]:
    username, role = _get_actor(request)
    admin = get_admin_context(request)
    if admin:
        can_moderate = bool(admin["is_super"] or int(admin["admin_level"]) >= 2)
        return username, "admin" if can_moderate else "admin_limited", can_moderate or username == author_username
    # 版主检查：用户是该板块的版主
    if username and category_slug:
        try:
            cat = ForumCategory.objects.get(slug=category_slug)
            if cat.moderators.filter(username=username).exists():
                return username, "moderator", True
        except ForumCategory.DoesNotExist:
            pass
    return username, role, username == author_username


def _record_moderation_action(*, target_type: str, target_id: int, action: str, admin_username: str, note: str = "") -> None:
    ForumModerationAction.objects.create(
        target_type=target_type,
        target_id=target_id,
        action=action,
        admin_username=admin_username,
        note=note[:1000],
    )


def _initials(username: str) -> str:
    parts = username.strip().split()
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()[:2]


_MENTION_RE = re.compile(r"(^|[^\w\u4e00-\u9fa5])@([A-Za-z0-9_\-\u4e00-\u9fa5]{2,32})")


def extract_mentioned_usernames(text: str) -> list[str]:
    """从文本中提取被 @ 的用户名（去重，保持出现顺序）。

    规则与前端 forum.js 的 renderInlineMarkdown 保持一致：
    @ 后跟 2-32 字符的中英文/数字/下划线/短横线，且前一个字符非单词字符。
    """
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for m in _MENTION_RE.finditer(text):
        name = m.group(2)
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _category_payload(cat: ForumCategory) -> dict:
    return {
        "id": cat.pk,
        "slug": cat.slug,
        "name": cat.name,
        "icon": cat.icon,
        "color": cat.color,
        "moderators": list(cat.moderators.values_list("username", flat=True)),
    }


def _profile_payload(user: User, *, include_private: bool = False) -> dict:
    display_name = (user.display_name or "").strip() or user.username
    payload = {
        "username": user.username,
        "display_name": display_name,
        "avatar_url": user.avatar_url or "",
        "background_url": user.background_url or "",
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


def _author_payload_for_user(user: User, showcase: dict | None = None, level: int = 0) -> dict:
    display_name = (user.display_name or "").strip() or user.username
    return {
        "username": user.username,
        "display_name": display_name,
        "avatar_url": user.avatar_url or "",
        "initials": _initials(display_name),
        "level": level,
        "showcase": showcase,
    }


def _author_payload(username: str, showcase: dict | None = None) -> dict:
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return {
            "username": username,
            "display_name": username,
            "avatar_url": "",
            "initials": _initials(username),
            "level": 0,
            "showcase": showcase,
        }
    try:
        from apps.points.models import PointAccount

        level = int(
            PointAccount.objects.filter(user_id=user.pk)
            .values_list("reputation_level", flat=True)
            .first()
            or 0
        )
    except Exception:
        logger.exception("读取论坛作者积分等级失败", extra={"username": username})
        level = 0
    return _author_payload_for_user(user, showcase, level)


def _authors_payload(usernames: list[str] | set[str]) -> dict[str, dict]:
    """Build author cards with one user query and one point-account query."""
    from apps.points.models import PointAccount

    names = set(usernames)
    if not names:
        return {}
    users = {user.username: user for user in User.objects.filter(username__in=names)}
    accounts = {
        account.user_id: account
        for account in PointAccount.objects.filter(user_id__in=[user.pk for user in users.values()])
    }
    result = {}
    for username in names:
        user = users.get(username)
        if user is None:
            result[username] = {
                "username": username,
                "display_name": username,
                "avatar_url": "",
                "initials": _initials(username),
                "level": 0,
                "showcase": None,
            }
            continue
        account = accounts.get(user.pk)
        result[username] = _author_payload_for_user(
            user,
            level=int(account.reputation_level or 0) if account else 0,
        )
    return result


def _showcase_map(usernames: list[str]) -> dict:
    """批量取作者佩戴中的勋章，避免列表页 N+1。"""
    from apps.gamification.models import UserStats

    result = {}
    for stats in UserStats.objects.filter(user__username__in=set(usernames)).select_related("user", "showcase"):
        if stats.showcase:
            result[stats.user.username] = {
                "code": stats.showcase.code,
                "name": stats.showcase.name,
                "icon": stats.showcase.icon,
                "tier": stats.showcase.tier,
            }
    return result


def _valid_profile_image_url(value: str) -> bool:
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


def _images_for_topics(topics: list[ForumTopic]) -> dict[int, list[dict]]:
    """Load all image references for a page in one query."""
    topic_ids: dict[int, list[int]] = {
        topic.pk: parse_image_ids(topic.images) for topic in topics
    }
    image_ids = {image_id for ids in topic_ids.values() for image_id in ids}
    rows = {row.pk: row for row in ForumImage.objects.filter(id__in=image_ids)}
    return {
        topic_id: [
            {"id": image_id, "url": f"/api/forum/images/{image_id}"}
            for image_id in ids
            if image_id in rows
        ]
        for topic_id, ids in topic_ids.items()
    }


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
    author_profile: dict | None = None,
    links: list[dict] | None = None,
    images: list[dict] | None = None,
    liked: bool | None = None,
    include_content: bool = True,
) -> dict:
    if like_count is None:
        like_count = topic.likes.count()
    if reply_count is None:
        reply_count = topic.reply_count
    if liked is None:
        liked = bool(liked_by and topic.likes.filter(username=liked_by).exists())
    if author_profile is None:
        author_profile = _author_payload(topic.author_username, author_showcase)
    if links is None:
        links = [_link_payload(link) for link in topic.links.all()]
    if images is None:
        images = _images_payload(topic)
    body = {
        "id": topic.pk,
        "title": topic.title,
        "excerpt": topic.content[:120] + ("…" if len(topic.content) > 120 else ""),
        "author": topic.author_username,
        "author_profile": author_profile,
        "initials": _initials(topic.author_username),
        "category": topic.category.name,
        "category_slug": topic.category.slug,
        "category_color": topic.category.color,
        "tags": topic.tag_list,
        "links": links,
        "images": images,
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
    if include_content:
        body["content"] = topic.content
    return body


def _reply_payload(
    reply: ForumReply,
    *,
    liked_by: str = "",
    like_count: int | None = None,
    author_profile: dict | None = None,
    liked: bool | None = None,
) -> dict:
    if like_count is None:
        like_count = reply.likes.count()
    if liked is None:
        liked = bool(liked_by and reply.likes.filter(username=liked_by).exists())
    if author_profile is None:
        author_profile = _author_payload(reply.author_username)
    return {
        "id": reply.pk,
        "topic_id": reply.topic_id,
        "author": reply.author_username,
        "author_profile": author_profile,
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
        logger.exception("读取论坛用户勋章或等级失败", extra={"username": user.username})
        profile["badges"] = []
        profile["level"] = 0
    try:
        from apps.gamification.services import showcase_payload

        profile["showcase"] = showcase_payload(user)
    except Exception:
        logger.exception("读取论坛用户展示勋章失败", extra={"username": user.username})
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
    background_url = str(body.get("background_url", body.get("backgroundUrl", ""))).strip()
    bio = str(body.get("bio", "")).strip()
    if len(display_name) > 100:
        return json_error("昵称最多 100 个字符")
    if len(avatar_url) > 500 or not _valid_profile_image_url(avatar_url):
        return json_error("头像地址必须是 HTTPS 地址或本站路径")
    if len(background_url) > 500 or not _valid_profile_image_url(background_url):
        return json_error("背景墙地址必须是 HTTPS 地址或本站路径")
    if len(bio) > 1000:
        return json_error("个人简介最多 1000 个字符")

    user = User.objects.get(username=username)
    user.display_name = display_name
    user.avatar_url = avatar_url
    user.background_url = background_url
    user.bio = bio
    user.save(update_fields=["display_name", "avatar_url", "background_url", "bio"])
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


@require_admin(level=3, super_only=True)
@require_http_methods(["PATCH"])
def set_category_moderators(request, category_id: int):
    """设置板块版主（仅 super admin 可调用）"""
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")
    moderator_usernames = body.get("moderators", [])
    if not isinstance(moderator_usernames, list):
        return json_error("moderators 必须是用户名列表")

    try:
        category = ForumCategory.objects.get(pk=category_id)
    except ForumCategory.DoesNotExist:
        return json_error("分类不存在", status=404)

    admin = request.kflow_admin

    # 找出新增和移除的版主
    current = set(category.moderators.values_list("username", flat=True))
    new = set(moderator_usernames)

    added = new - current
    removed = current - new

    # 更新多对多关系
    category.moderators.set(User.objects.filter(username__in=moderator_usernames))

    # 发放新成就 & 回收旧成就
    for username in added:
        user = User.objects.filter(username=username).first()
        if user:
            _grant_board_mod_achievement(user, category.slug)
            _record_moderation_action(
                target_type="category",
                target_id=category.pk,
                action="moderator_added",
                admin_username=admin["username"],
                note=f"添加版主 {username}",
            )

    for username in removed:
        user = User.objects.filter(username=username).first()
        if user:
            _revoke_board_mod_achievement(user, category.slug)
            _record_moderation_action(
                target_type="category",
                target_id=category.pk,
                action="moderator_removed",
                admin_username=admin["username"],
                note=f"移除版主 {username}",
            )

    return json_ok({"moderators": list(category.moderators.values_list("username", flat=True))})


def _grant_board_mod_achievement(user, category_slug: str) -> None:
    """发放板块版主成就"""
    slug_to_code = {
        "product": "mod_product",
        "research": "mod_research",
        "agent": "mod_agent",
        "hardware": "mod_hardware",
    }
    code = slug_to_code.get(category_slug)
    if not code:
        return
    try:
        from apps.gamification.models import Achievement, UserAchievement

        achievement = Achievement.objects.filter(code=code, is_active=True).first()
        if achievement:
            UserAchievement.objects.get_or_create(user=user, achievement=achievement)
    except Exception:
        pass


def _revoke_board_mod_achievement(user, category_slug: str) -> None:
    """回收板块版主成就"""
    slug_to_code = {
        "product": "mod_product",
        "research": "mod_research",
        "agent": "mod_agent",
        "hardware": "mod_hardware",
    }
    code = slug_to_code.get(category_slug)
    if not code:
        return
    try:
        from apps.gamification.models import Achievement, UserAchievement

        achievement = Achievement.objects.filter(code=code, is_active=True).first()
        if achievement:
            UserAchievement.objects.filter(user=user, achievement=achievement).delete()
    except Exception:
        pass


# ── topic list & detail ────────────────────────────────────────────────────────

@require_GET
def topics(request):
    username, _ = _get_actor(request)

    from .models import TopicBoost

    active_boosts = TopicBoost.objects.filter(
        topic_id=OuterRef("pk"),
        status=TopicBoost.STATUS_ACTIVE,
        ends_at__gt=django_timezone.now(),
    )
    qs = (
        ForumTopic.objects.filter(status=ForumTopic.STATUS_OPEN)
        .select_related("category")
        .annotate(has_active_boost=Exists(active_boosts))
    )

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
        qs = qs.order_by("-hot_score", "-created_at", "-pk")
    elif view == "boosted":
        qs = qs.filter(has_active_boost=True).order_by("-hot_score", "-created_at", "-pk")
    else:
        qs = qs.order_by("-is_pinned", "-created_at", "-pk")

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
    images_map = _images_for_topics(topic_list)
    author_map = _authors_payload([t.author_username for t in topic_list])
    showcase_map = _showcase_map({t.author_username for t in topic_list})
    for author, showcase in showcase_map.items():
        if author in author_map:
            author_map[author]["showcase"] = showcase
    items = []
    for t in topic_list:
        p = _topic_payload(
            t,
            like_count=like_counts.get(t.pk, 0),
            reply_count=reply_counts.get(t.pk, 0),
            author_profile=author_map.get(t.author_username),
            links=links_map.get(t.pk, []),
            images=images_map.get(t.pk, []),
            liked=t.pk in liked_set,
            include_content=False,
        )
        p["boosted"] = bool(getattr(t, "has_active_boost", False))
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

    try:
        reply_page = max(1, int(request.GET.get("reply_page", 1)))
        reply_page_size = min(
            REPLY_PAGE_SIZE_MAX,
            max(1, int(request.GET.get("reply_page_size", REPLY_PAGE_SIZE_DEFAULT))),
        )
    except ValueError:
        reply_page, reply_page_size = 1, REPLY_PAGE_SIZE_DEFAULT

    # Count a detail visit once; fetching another reply page must not inflate views.
    viewer_key = username or request.COOKIES.get("kflow_viewer", "") or _anon_viewer_key(request)
    if reply_page == 1:
        ForumTopic.objects.filter(pk=topic_id).update(views=F("views") + 1)
        try:
            record_dedup_view(topic, viewer_key)
        except Exception:
            logger.exception("记录论坛去重浏览失败", extra={"topic_id": topic_id})

    topic.refresh_from_db(fields=["views", "updated_at"])
    reply_queryset = topic.replies.filter(is_deleted=False).order_by("created_at", "pk")
    reply_total = reply_queryset.count()
    reply_offset = (reply_page - 1) * reply_page_size
    replies = list(reply_queryset[reply_offset : reply_offset + reply_page_size])
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
    author_map = _authors_payload([topic.author_username, *(reply.author_username for reply in replies)])
    showcase_map = _showcase_map(author_map.keys())
    for author, showcase in showcase_map.items():
        if author in author_map:
            author_map[author]["showcase"] = showcase
    topic_links = _links_for_topics([topic.pk]).get(topic.pk, [])
    topic_images = _images_for_topics([topic]).get(topic.pk, [])
    payload = _topic_payload(
        topic,
        liked=bool(username and ForumLike.objects.filter(topic=topic, username=username).exists()),
        author_profile=author_map.get(topic.author_username),
        links=topic_links,
        images=topic_images,
    )
    payload["boosted"] = bool(topic.active_boost())
    payload["replies_detail"] = [
        _reply_payload(
            r,
            like_count=reply_like_counts.get(r.pk, 0),
            author_profile=author_map.get(r.author_username),
            liked=r.pk in liked_reply_ids,
        )
        for r in replies
    ]
    payload["reply_page"] = reply_page
    payload["reply_page_size"] = reply_page_size
    payload["reply_total"] = reply_total
    payload["reply_has_next"] = reply_offset + reply_page_size < reply_total
    response = json_ok({"topic": payload})
    if not username and viewer_key:
        response.set_cookie("kflow_viewer", viewer_key, max_age=365 * 86400, samesite="Lax", httponly=True)
    return response


def _anon_viewer_key(request) -> str:
    existing = request.COOKIES.get("kflow_viewer", "")
    if existing:
        return existing
    return f"anon-{secrets.token_hex(8)}"


# ── topic / reply lifecycle and reports ──────────────────────────────────────


def _validate_topic_edit(body: dict, topic: ForumTopic) -> tuple[str, str, str] | dict:
    title = str(body.get("title", topic.title)).strip()
    content = str(body.get("content", topic.content)).strip()
    tags_raw = str(body.get("tags", topic.tags)).strip()
    if not title:
        return {"error": "标题不能为空"}
    if len(title) > 256:
        return {"error": "标题最多 256 个字符"}
    if not content:
        return {"error": "内容不能为空"}
    if len(content) > 20000:
        return {"error": "内容最多 20000 个字符"}
    tags = ",".join(t[:16] for t in [x.strip() for x in tags_raw.split(",") if x.strip()][:5])
    return title, content, tags


@require_http_methods(["PATCH", "PUT", "DELETE"])
def manage_topic(request, topic_id: int):
    topic = ForumTopic.objects.filter(pk=topic_id).first()
    if topic is None:
        return json_error("话题不存在", status=404)
    username, role, allowed = _can_manage_forum_object(request, topic.author_username, topic.category.slug)
    if not username:
        return json_error("请先登录", status=401)
    if not allowed:
        return json_error("没有权限管理该话题", status=403)

    if request.method == "DELETE":
        if topic.status == ForumTopic.STATUS_DELETED:
            return json_ok({"deleted": True})
        with transaction.atomic():
            topic.status = ForumTopic.STATUS_DELETED
            topic.save(update_fields=["status", "updated_at"])
            if role == "admin":
                _record_moderation_action(
                    target_type=ForumReport.TARGET_TOPIC,
                    target_id=topic.pk,
                    action="topic_deleted",
                    admin_username=username,
                    note="管理员下线话题",
                )
        refunded = 0
        try:
            from .services import refund_active_boosts

            refunded = refund_active_boosts(topic, reason="话题已删除")
        except Exception:
            logger.exception("删除话题后退还加热失败", extra={"topic_id": topic_id})
            refunded = 0
        return json_ok({"deleted": True, "refunded_boosts": refunded})

    if topic.status == ForumTopic.STATUS_DELETED:
        return json_error("话题不存在", status=404)

    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")
    values = _validate_topic_edit(body, topic)
    if isinstance(values, dict):
        return json_error(values["error"])
    title, content, tags = values
    topic.title = title
    topic.content = content
    topic.tags = tags
    topic.save(update_fields=["title", "content", "tags", "updated_at"])
    if role == "admin":
        _record_moderation_action(
            target_type=ForumReport.TARGET_TOPIC,
            target_id=topic.pk,
            action="topic_edited",
            admin_username=username,
        )
    return json_ok({"topic": _topic_payload(topic)})


@require_http_methods(["PATCH", "PUT", "DELETE"])
def manage_reply(request, reply_id: int):
    reply = ForumReply.objects.select_related("topic").filter(pk=reply_id).first()
    if reply is None or reply.topic.status == ForumTopic.STATUS_DELETED:
        return json_error("回复不存在", status=404)
    username, role, allowed = _can_manage_forum_object(request, reply.author_username, reply.topic.category.slug)
    if not username:
        return json_error("请先登录", status=401)
    if not allowed:
        return json_error("没有权限管理该回复", status=403)
    if request.method == "DELETE":
        if reply.is_deleted:
            return json_ok({"deleted": True})
        reply.is_deleted = True
        reply.save(update_fields=["is_deleted", "updated_at"])
        ForumTopic.objects.filter(pk=reply.topic_id).update(updated_at=reply.updated_at)
        if role == "admin":
            _record_moderation_action(
                target_type=ForumReport.TARGET_REPLY,
                target_id=reply.pk,
                action="reply_deleted",
                admin_username=username,
                note="管理员删除回复",
            )
        return json_ok({"deleted": True})
    if reply.is_deleted:
        return json_error("回复不存在", status=404)
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")
    content = str(body.get("content", "")).strip()
    if not content:
        return json_error("回复内容不能为空")
    if len(content) > 10000:
        return json_error("回复最多 10000 个字符")
    reply.content = content
    reply.save(update_fields=["content", "updated_at"])
    ForumTopic.objects.filter(pk=reply.topic_id).update(updated_at=reply.updated_at)
    if role == "admin":
        _record_moderation_action(
            target_type=ForumReport.TARGET_REPLY,
            target_id=reply.pk,
            action="reply_edited",
            admin_username=username,
        )
    return json_ok({"reply": _reply_payload(reply)})


def _create_report(request, *, target_type: str, target_id: int):
    username, _ = _get_actor(request)
    if not username:
        return json_error("请先登录后再举报", status=401)
    if target_type == ForumReport.TARGET_TOPIC:
        target = ForumTopic.objects.filter(pk=target_id, status=ForumTopic.STATUS_OPEN).first()
    else:
        target = ForumReply.objects.select_related("topic").filter(
            pk=target_id, is_deleted=False, topic__status=ForumTopic.STATUS_OPEN
        ).first()
    if target is None:
        return json_error("内容不存在或已下线", status=404)
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")
    reason = str(body.get("reason", "other")).strip().lower()
    details = str(body.get("details", "")).strip()
    if reason not in REPORT_REASONS:
        return json_error("举报原因不合法")
    if len(details) > 500:
        return json_error("补充说明最多 500 个字符")
    report, created = ForumReport.objects.get_or_create(
        target_type=target_type,
        target_id=target_id,
        reporter_username=username,
        defaults={"reason": reason, "details": details},
    )
    if not created:
        return json_ok({"reported": True, "duplicate": True})
    return json_ok({"reported": True, "report_id": report.pk}, status=201)


@require_POST
def report_topic(request, topic_id: int):
    return _create_report(request, target_type=ForumReport.TARGET_TOPIC, target_id=topic_id)


@require_POST
def report_reply(request, reply_id: int):
    return _create_report(request, target_type=ForumReport.TARGET_REPLY, target_id=reply_id)


def _report_payload(report: ForumReport, target=None) -> dict:
    payload = {
        "id": report.pk,
        "target_type": report.target_type,
        "target_id": report.target_id,
        "reporter_username": report.reporter_username,
        "reason": report.reason,
        "details": report.details,
        "status": report.status,
        "reviewer_username": report.reviewer_username,
        "review_note": report.review_note,
        "created_at": report.created_at.isoformat(),
        "reviewed_at": report.reviewed_at.isoformat() if report.reviewed_at else None,
    }
    if report.target_type == ForumReport.TARGET_TOPIC:
        payload["target_title"] = getattr(target, "title", "")
        payload["target_author"] = getattr(target, "author_username", "")
        payload["target_excerpt"] = getattr(target, "content", "")[:240]
    else:
        payload["target_title"] = getattr(getattr(target, "topic", None), "title", "")
        payload["target_author"] = getattr(target, "author_username", "")
        payload["target_excerpt"] = getattr(target, "content", "")[:240]
    return payload


@require_admin(level=2)
@require_GET
def admin_forum_reports(request):
    status = request.GET.get("status", ForumReport.STATUS_PENDING).strip()
    if status not in {"", "all", ForumReport.STATUS_PENDING, ForumReport.STATUS_RESOLVED, ForumReport.STATUS_REJECTED}:
        return json_error("举报状态不合法")
    queryset = ForumReport.objects.order_by("-created_at")
    if status and status != "all":
        queryset = queryset.filter(status=status)
    reports = list(queryset[:100])
    topic_ids = [report.target_id for report in reports if report.target_type == ForumReport.TARGET_TOPIC]
    reply_ids = [report.target_id for report in reports if report.target_type == ForumReport.TARGET_REPLY]
    topics = {topic.pk: topic for topic in ForumTopic.objects.filter(pk__in=topic_ids)}
    replies = {
        reply.pk: reply
        for reply in ForumReply.objects.filter(pk__in=reply_ids).select_related("topic")
    }
    return json_ok({
        "items": [
            _report_payload(report, topics.get(report.target_id) if report.target_type == ForumReport.TARGET_TOPIC else replies.get(report.target_id))
            for report in reports
        ],
        "total": queryset.count(),
    })


@require_admin(level=2)
@require_POST
def admin_review_forum_report(request, report_id: int):
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("无效的请求数据")
    decision = str(body.get("decision", "rejected")).strip().lower()
    remove = bool(body.get("remove", False))
    note = str(body.get("note", "")).strip()[:1000]
    if decision not in {ForumReport.STATUS_RESOLVED, ForumReport.STATUS_REJECTED}:
        return json_error("处理结果不合法")
    admin = request.kflow_admin
    refund_count = 0
    with transaction.atomic():
        report = ForumReport.objects.select_for_update().filter(pk=report_id).first()
        if report is None:
            return json_error("举报记录不存在", status=404)
        if report.status != ForumReport.STATUS_PENDING:
            return json_ok({"status": report.status, "removed": False, "refunded_boosts": 0, "replayed": True})
        report.status = decision
        report.reviewer_username = admin["username"]
        report.review_note = note
        report.reviewed_at = django_timezone.now()
        report.save(update_fields=["status", "reviewer_username", "review_note", "reviewed_at"])
        if decision == ForumReport.STATUS_RESOLVED and remove:
            if report.target_type == ForumReport.TARGET_TOPIC:
                target = ForumTopic.objects.filter(pk=report.target_id).first()
                if target and target.status != ForumTopic.STATUS_DELETED:
                    target.status = ForumTopic.STATUS_DELETED
                    target.save(update_fields=["status", "updated_at"])
                    _record_moderation_action(
                        target_type=report.target_type,
                        target_id=report.target_id,
                        action="report_removed_topic",
                        admin_username=admin["username"],
                        note=note,
                    )
            else:
                target = ForumReply.objects.filter(pk=report.target_id).first()
                if target and not target.is_deleted:
                    target.is_deleted = True
                    target.save(update_fields=["is_deleted", "updated_at"])
                    ForumTopic.objects.filter(pk=target.topic_id).update(updated_at=target.updated_at)
                    _record_moderation_action(
                        target_type=report.target_type,
                        target_id=report.target_id,
                        action="report_removed_reply",
                        admin_username=admin["username"],
                        note=note,
                    )
        _record_moderation_action(
            target_type=report.target_type,
            target_id=report.target_id,
            action=f"report_{decision}",
            admin_username=admin["username"],
            note=note,
        )
    if decision == ForumReport.STATUS_RESOLVED and remove and report.target_type == ForumReport.TARGET_TOPIC:
        try:
            from .services import refund_active_boosts

            topic = ForumTopic.objects.get(pk=report.target_id)
            refund_count = refund_active_boosts(topic, reason="举报处理下线")
        except Exception:
            logger.exception("举报下线后退还加热失败", extra={"report_id": report_id, "topic_id": report.target_id})
            refund_count = 0
    return json_ok({"status": report.status, "removed": bool(decision == ForumReport.STATUS_RESOLVED and remove), "refunded_boosts": refund_count})


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

    # @提及通知（帖子正文里提到的人）
    mention_names = extract_mentioned_usernames(content) + extract_mentioned_usernames(title)
    if mention_names:
        mentioned_users = User.objects.filter(username__in=mention_names)
        link = f"/forum?topic={topic.pk}"
        excerpt = (content[:80] or title).replace("\n", " ")
        for mentioned in mentioned_users:
            notify_user(
                recipient=mentioned, type_="mention",
                title=f"{username} 在新帖「{title[:40]}」中提到了你",
                body=excerpt,
                link=link, actor_username=username,
            )

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

    # @提及通知：给回复里所有 @username 发 mention 通知（自身/话题作者已自动跳过）
    mention_names = extract_mentioned_usernames(content)
    if mention_names:
        mentioned_users = User.objects.filter(username__in=mention_names)
        link = f"/forum?topic={topic.pk}"
        excerpt = content[:80].replace("\n", " ")
        for mentioned in mentioned_users:
            notify_user(
                recipient=mentioned, type_="mention",
                title=f"{username} 在「{topic.title[:40]}」的回复中提到了你",
                body=excerpt,
                link=link, actor_username=username,
            )
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
        upload.seek(0)
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
    idempotency_key = str(
        body.get("idempotency_key", body.get("idempotencyKey", ""))
        or request.headers.get("X-Idempotency-Key", "")
    ).strip()
    if len(idempotency_key) > 120:
        return json_error("幂等标识最多 120 个字符")
    try:
        user_obj = User.objects.get(username=username)
    except User.DoesNotExist:
        return json_error("用户不存在", status=404)
    try:
        boost, info = purchase_boost(
            user=user_obj,
            topic=topic,
            tier=tier,
            idempotency_key=idempotency_key,
        )
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
