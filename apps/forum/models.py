# pyright: reportMissingImports=false
"""Forum models: categories, topics, replies, likes."""
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
    tags = models.CharField(max_length=256, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "forum_topics"
        ordering = ["-is_pinned", "-created_at"]
        indexes = [
            models.Index(fields=["category", "status", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["is_featured", "status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def reply_count(self) -> int:
        return self.replies.filter(is_deleted=False).count()

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


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
