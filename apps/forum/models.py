# pyright: reportMissingImports=false
"""Forum models: categories, topics, replies, likes, images, links, boosts."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class ForumCategory(models.Model):
    """Discussion categories shown in the left sidebar."""

    slug = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    icon = models.CharField(max_length=8, default="💬")
    color = models.CharField(max_length=32, default="#657080")
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_categories"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name


class ForumTopic(models.Model):
    """A discussion thread posted by a user or an admin."""

    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_DELETED = "deleted"

    category = models.ForeignKey(
        ForumCategory,
        on_delete=models.PROTECT,
        related_name="topics",
        db_column="category_id",
    )
    title = models.CharField(max_length=256)
    content = models.TextField()
    author_username = models.CharField(max_length=150)
    is_pinned = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    status = models.CharField(max_length=16, default=STATUS_OPEN)
    views = models.PositiveIntegerField(default=0)
    dedup_views = models.PositiveIntegerField(default=0)
    hot_score = models.FloatField(default=0, db_index=True)
    tags = models.CharField(max_length=256, blank=True, default="")
    images = models.TextField(blank=True, default="")  # JSON array of image ids
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "forum_topics"
        ordering = ["-is_pinned", "-created_at"]
        indexes = [
            models.Index(fields=["category", "status", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["is_featured", "status", "-created_at"]),
            models.Index(fields=["status", "-hot_score"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def reply_count(self) -> int:
        return self.replies.filter(is_deleted=False).count()

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def image_ids(self) -> list[int]:
        import json

        try:
            raw = json.loads(self.images) if self.images else []
        except (ValueError, TypeError):
            return []
        return [int(i) for i in raw if isinstance(i, (int, str)) and str(i).isdigit()][:9]

    def active_boost(self):
        from django.utils import timezone

        return self.boosts.filter(
            status=TopicBoost.STATUS_ACTIVE, ends_at__gt=timezone.now()
        ).order_by("-ends_at").first()

    def boost_score_active(self) -> int:
        from django.utils import timezone

        total = 0
        for boost in self.boosts.filter(status=TopicBoost.STATUS_ACTIVE, ends_at__gt=timezone.now()):
            total += boost.boost_score
        return total


class ForumTopicLink(models.Model):
    """External project link (GitHub / Gitee / live site) attached to a topic."""

    TYPE_GITHUB = "github"
    TYPE_GITEE = "gitee"
    TYPE_LIVE = "live"
    TYPE_OTHER = "other"

    topic = models.ForeignKey(
        ForumTopic,
        on_delete=models.CASCADE,
        related_name="links",
        db_column="topic_id",
    )
    url = models.URLField(max_length=500)
    link_type = models.CharField(max_length=16, default=TYPE_OTHER)
    display_name = models.CharField(max_length=120, blank=True, default="")
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_topic_links"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["topic", "url"], name="uq_topic_link_url"),
        ]

    def __str__(self) -> str:
        return f"{self.link_type}: {self.url}"


class ForumReply(models.Model):
    """A reply (post) inside a topic."""

    topic = models.ForeignKey(
        ForumTopic,
        on_delete=models.CASCADE,
        related_name="replies",
        db_column="topic_id",
    )
    author_username = models.CharField(max_length=150)
    content = models.TextField()
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "forum_replies"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Reply by {self.author_username} on topic {self.topic_id}"


class ForumLike(models.Model):
    """Heart / like on a topic (one per user per topic)."""

    topic = models.ForeignKey(
        ForumTopic,
        on_delete=models.CASCADE,
        related_name="likes",
        db_column="topic_id",
    )
    username = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_likes"
        constraints = [
            models.UniqueConstraint(fields=["topic", "username"], name="uq_forum_like_topic_user"),
        ]

    def __str__(self) -> str:
        return f"{self.username} liked topic {self.topic_id}"


class ForumReplyLike(models.Model):
    """Like on a reply (one per user per reply)."""

    reply = models.ForeignKey(
        ForumReply,
        on_delete=models.CASCADE,
        related_name="likes",
        db_column="reply_id",
    )
    username = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_reply_likes"
        constraints = [
            models.UniqueConstraint(fields=["reply", "username"], name="uq_forum_reply_like_user"),
        ]

    def __str__(self) -> str:
        return f"{self.username} liked reply {self.reply_id}"


class ForumImage(models.Model):
    """Image uploaded for a forum topic; served through /api/forum/images/<id>."""

    uploader_username = models.CharField(max_length=150)
    file = models.FileField(upload_to="forum/%Y/%m/", max_length=300)
    content_type = models.CharField(max_length=64, default="image/jpeg")
    file_size = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_images"

    def __str__(self) -> str:
        return f"forum image {self.pk} by {self.uploader_username}"


class TopicViewLog(models.Model):
    """Deduplicated daily view counter backing ForumTopic.dedup_views."""

    topic = models.ForeignKey(
        ForumTopic,
        on_delete=models.CASCADE,
        related_name="view_logs",
        db_column="topic_id",
    )
    viewer_key = models.CharField(max_length=180)
    view_date = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_topic_view_logs"
        constraints = [
            models.UniqueConstraint(fields=["topic", "viewer_key", "view_date"], name="uq_topic_view_daily"),
        ]
        indexes = [models.Index(fields=["topic", "view_date"])]


class TopicBoost(models.Model):
    """Paid topic promotion ("抖+" style): spend points to gain hot-score boost."""

    STATUS_ACTIVE = "active"
    STATUS_ENDED = "ended"
    STATUS_REFUNDED = "refunded"

    TIER_SMALL = "small"
    TIER_MEDIUM = "medium"
    TIER_LARGE = "large"

    topic = models.ForeignKey(
        ForumTopic,
        on_delete=models.CASCADE,
        related_name="boosts",
        db_column="topic_id",
    )
    username = models.CharField(max_length=150)
    tier = models.CharField(max_length=16, default=TIER_SMALL)
    points_cost = models.PositiveIntegerField(default=0)
    boost_score = models.PositiveIntegerField(default=0)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=16, default=STATUS_ACTIVE)
    ledger_id = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_topic_boosts"
        indexes = [models.Index(fields=["status", "ends_at"])]

    def __str__(self) -> str:
        return f"boost[{self.tier}] topic={self.topic_id} by {self.username}"


class ForumReport(models.Model):
    """A user report for a topic or reply awaiting moderator review."""

    TARGET_TOPIC = "topic"
    TARGET_REPLY = "reply"
    STATUS_PENDING = "pending"
    STATUS_RESOLVED = "resolved"
    STATUS_REJECTED = "rejected"

    target_type = models.CharField(max_length=16)
    target_id = models.PositiveIntegerField()
    reporter_username = models.CharField(max_length=150)
    reason = models.CharField(max_length=32)
    details = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, default=STATUS_PENDING)
    reviewer_username = models.CharField(max_length=150, blank=True, default="")
    review_note = models.TextField(blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_reports"
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_id", "reporter_username"],
                name="uq_forum_reporter_target",
            ),
        ]
        indexes = [models.Index(fields=["status", "-created_at"])]


class ForumModerationAction(models.Model):
    """Immutable audit record for moderator changes to forum content."""

    target_type = models.CharField(max_length=16)
    target_id = models.PositiveIntegerField()
    action = models.CharField(max_length=32)
    admin_username = models.CharField(max_length=150)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "forum_moderation_actions"
        indexes = [models.Index(fields=["target_type", "target_id", "-created_at"])]
