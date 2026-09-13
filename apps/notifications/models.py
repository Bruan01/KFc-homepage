# pyright: reportMissingImports=false
"""In-site notification models (站内信)."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class Notification(models.Model):
    TYPE_CHOICES = (
        ("badge", "成就勋章"),
        ("level", "等级提升"),
        ("like", "收到点赞"),
        ("reply", "收到评论"),
        ("reply_like", "评论被赞"),
        ("sale", "商品售出"),
        ("system", "系统通知"),
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="user_id",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default="system")
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=300, blank=True, default="")
    link = models.CharField(max_length=300, blank=True, default="")
    actor_username = models.CharField(max_length=150, blank=True, default="")
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self) -> str:
        return f"[{self.type}] to {self.recipient_id}: {self.title}"
