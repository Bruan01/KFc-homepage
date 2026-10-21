"""Batched feed serialization and shared visibility rules."""
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Prefetch, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import User
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


def authors_payload(usernames):
    users = User.objects.filter(username__in=set(usernames)).only("username", "display_name", "avatar_url")
    result = {name: {"username": name, "display_name": name, "avatar_url": ""} for name in usernames}
    for user in users:
        result[user.username] = {
            "username": user.username,
            "display_name": user.display_name.strip() or user.username,
            "avatar_url": user.avatar_url or "",
        }
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
    ).prefetch_related(Prefetch("attachments", queryset=MurmurImage.objects.select_related("image")))


def feed_queryset(username):
    return _with_engagement(visible_posts(username), username)


def moderation_queryset(username):
    return _with_engagement(Murmur.objects.all(), username)


def images_payload(row):
    return [{"id": a.image_id, "url": f"/api/forum/images/{a.image_id}", "width": a.image.width, "height": a.image.height}
            for a in row.attachments.all()]


def post_payload(row, authors, username):
    payload = {
        "id": row.pk,
        "author": authors[row.author_username],
        "content": row.content,
        "created_at": row.created_at,
        "images": images_payload(row),
        "like_count": row.like_count,
        "comment_count": row.comment_count,
        "liked": row.liked,
        "can_delete": row.author_username == username,
        "is_own": row.author_username == username,
        "is_deleted": row.is_deleted,
    }
    if row.is_deleted:
        payload.update({
            "deleted_at": row.deleted_at,
            "deleted_by": row.deleted_by,
            "deletion_reason": row.deletion_reason,
        })
    return payload


def serialize_posts(rows, username):
    authors = authors_payload([row.author_username for row in rows])
    return [post_payload(row, authors, username) for row in rows]
