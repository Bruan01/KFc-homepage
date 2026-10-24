"""Batched feed serialization and shared visibility rules."""
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Prefetch, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import User, UserFollow
from apps.accounts.official import official_account_id
from apps.accounts.mentions import names as mention_names, resolve_many
from apps.core.permissions import get_admin_context
from .models import Murmur, MurmurBlock, MurmurComment, MurmurImage, MurmurLike


def actor(request):
    admin = get_admin_context(request)
    if admin:
        return admin["username"]
    return request.user.username if request.user.is_authenticated else ""


def can_moderate(request):
    admin = get_admin_context(request)
    return bool(admin and (admin["is_super"] or admin["admin_level"] >= 2))


def appeal_deadline() -> str:
    return (timezone.now() + timedelta(days=settings.MURMUR_APPEAL_DAYS)).isoformat()


def appeal_window_open(value: str) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value) > timezone.now()
    except (TypeError, ValueError):
        return False


def authors_payload(usernames, viewer=""):
    official_id = official_account_id()
    users = User.objects.filter(username__in=set(usernames)).only("username", "display_name", "avatar_url")
    result = {name: {"username": name, "display_name": name, "avatar_url": ""} for name in usernames}
    for user in users:
        result[user.username] = {
            "username": user.username,
            "display_name": user.display_name.strip() or user.username,
            "avatar_url": user.avatar_url or "",
            "is_official": user.pk == official_id,
        }
    followed = set(UserFollow.objects.filter(follower__username=viewer, following__username__in=result).values_list("following__username", flat=True)) if viewer else set()
    for name in result:
        result[name]["is_following"] = name in followed
    return result


def visible_posts(username):
    qs = Murmur.objects.filter(is_deleted=False)
    if username:
        qs = qs.exclude(author_username__in=MurmurBlock.objects.filter(username=username).values("blocked_username"))
    return qs


def _with_engagement(qs, username):
    likes = MurmurLike.objects.filter(murmur_id=OuterRef("pk")).order_by().values("murmur_id").annotate(n=Count("pk")).values("n")
    comments = MurmurComment.objects.filter(murmur_id=OuterRef("pk"), is_deleted=False).order_by().values("murmur_id").annotate(n=Count("pk")).values("n")
    return qs.annotate(
        # Separate subqueries avoid a likes × comments join on busy posts.
        like_count=Coalesce(Subquery(likes), 0),
        comment_count=Coalesce(Subquery(comments), 0),
        liked=Exists(MurmurLike.objects.filter(murmur_id=OuterRef("pk"), username=username)),
    ).prefetch_related(
        Prefetch("attachments", queryset=MurmurImage.objects.select_related("image")),
        "videos",
    )


def feed_queryset(username):
    return _with_engagement(visible_posts(username), username)


def moderation_queryset(username):
    return _with_engagement(Murmur.objects.all(), username)


def images_payload(row):
    return [{"id": a.image_id, "url": f"/api/forum/images/{a.image_id}", "width": a.image.width, "height": a.image.height}
            for a in row.attachments.all()]


def video_payload(video):
    return {
        "id": video.pk,
        "url": f"/api/murmurs/videos/{video.pk}",
        "poster": f"/api/murmurs/videos/{video.pk}/poster" if video.poster else "",
        "duration": round(video.duration, 1),
        "width": video.width,
        "height": video.height,
    }


def videos_payload(row):
    # Comments have no videos; only murmurs own a video relation.
    return [video_payload(video) for video in row.videos.all()] if hasattr(row, "videos") else []


def post_payload(row, authors, username, mentions=None):
    payload = {
        "id": row.pk,
        "author": authors[row.author_username],
        "content": row.content,
        "created_at": row.created_at,
        "images": images_payload(row),
        "videos": videos_payload(row),
        "like_count": row.like_count,
        "comment_count": row.comment_count,
        "liked": row.liked,
        "can_delete": row.author_username == username,
        "is_own": row.author_username == username,
        "is_deleted": row.is_deleted,
        "pinned": row.is_pinned,
        "mention_usernames": sorted(mention_names(row.content) & (mentions or {}).get(row.author_username, set())),
    }
    if row.is_deleted:
        payload.update({
            "deleted_at": row.deleted_at,
            "deleted_by": row.deleted_by,
            "deletion_reason": row.deletion_reason,
        })
    return payload


def serialize_posts(rows, username):
    authors = authors_payload([row.author_username for row in rows], username)
    mentions = resolve_many([(row.author_username, row.content) for row in rows])
    return [post_payload(row, authors, username, mentions) for row in rows]
