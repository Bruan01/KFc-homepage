from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models


def image_upload_to(instance: "ImageGenerationJob", filename: str) -> str:
    extension = instance.output_format or Path(filename).suffix.lstrip(".") or "png"
    return f"imaging/{instance.user_id}/{instance.created_at:%Y/%m}/{instance.id}.{extension}"


class ImageGenerationJob(models.Model):
    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    STATUS_CHOICES = (
        (QUEUED, "排队中"),
        (GENERATING, "生成中"),
        (COMPLETED, "已完成"),
        (FAILED, "失败"),
    )

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="image_generation_jobs",
    )
    prompt = models.TextField()
    size = models.CharField(max_length=20)
    quality = models.CharField(max_length=20)
    output_format = models.CharField(max_length=10)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=QUEUED)
    points_cost = models.PositiveIntegerField(default=0)
    point_ledger = models.ForeignKey(
        "points.PointLedger",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="image_generation_jobs",
    )
    idempotency_key = models.CharField(max_length=160)
    image = models.FileField(upload_to=image_upload_to, blank=True)
    image_sha256 = models.CharField(max_length=64, blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"], name="imaging_user_created_idx"),
            models.Index(fields=["status", "created_at"], name="imaging_status_created_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uq_imaging_user_idempotency",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.id} ({self.status})"
