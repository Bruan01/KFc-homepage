from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models


def image_upload_to(instance: "ImageGenerationJob", filename: str) -> str:
    extension = instance.output_format or Path(filename).suffix.lstrip(".") or "png"
    return f"imaging/{instance.user_id}/{instance.created_at:%Y/%m}/{instance.id}.{extension}"


def reference_upload_to(instance: "ImageGenerationReference", filename: str) -> str:
    extension = Path(filename).suffix.lower() or ".png"
    return f"imaging/references/{instance.job.user_id}/{instance.job.created_at:%Y/%m}/{instance.id}{extension}"


class ImagingProvider(models.Model):
    """A separately configured image-generation endpoint in the service pool."""

    name = models.CharField(max_length=120, unique=True)
    enabled = models.BooleanField(default=True)
    base_url = models.CharField(max_length=500)
    api_key = models.TextField(blank=True, default="")
    model = models.CharField(max_length=120)
    timeout_seconds = models.PositiveIntegerField(default=360)
    weight = models.PositiveIntegerField(default=1)
    priority = models.IntegerField(default=100)
    schedule_current_weight = models.IntegerField(default=0)
    consecutive_failures = models.PositiveIntegerField(default=0)
    circuit_open_until = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["enabled", "circuit_open_until"], name="imaging_provider_avail_idx"),
            models.Index(fields=["priority", "id"], name="imaging_provider_order_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class ImagingTemplate(models.Model):
    """An administrator-managed prompt recipe displayed by the imaging studio."""

    TYPE_PROMPT = "prompt"
    TYPE_SKILL = "skill"
    TYPE_CHOICES = ((TYPE_PROMPT, "Prompt 模板"), (TYPE_SKILL, "Skill 模板"))

    key = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    template_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_PROMPT)
    skill_key = models.CharField(max_length=120, blank=True, default="")
    category = models.CharField(max_length=80, blank=True, default="")
    description = models.CharField(max_length=500, blank=True, default="")
    accent = models.CharField(max_length=40, blank=True, default="")
    cover_url = models.CharField(max_length=500, blank=True, default="")
    fields = models.JSONField(default=list)
    prompt_template = models.TextField()
    reference_required = models.BooleanField(default=False)
    reference_max_count = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=100)
    is_system = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["enabled", "sort_order", "id"], name="imaging_template_order_idx")]
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name


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
    provider = models.ForeignKey(
        ImagingProvider,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generation_jobs",
    )
    prompt = models.TextField()
    original_prompt = models.TextField(blank=True, default="")
    template_key = models.CharField(max_length=80, blank=True, default="")
    template_name = models.CharField(max_length=120, blank=True, default="")
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


class ImageGenerationReference(models.Model):
    """A private source or style image supplied by a user for an imaging job."""

    job = models.ForeignKey(ImageGenerationJob, on_delete=models.CASCADE, related_name="references")
    image = models.FileField(upload_to=reference_upload_to)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.original_name


class ImagingProviderAttempt(models.Model):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STATUS_CHOICES = (
        (SUCCEEDED, "成功"),
        (FAILED, "失败"),
    )

    job = models.ForeignKey(ImageGenerationJob, on_delete=models.CASCADE, related_name="provider_attempts")
    provider = models.ForeignKey(
        ImagingProvider,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attempts",
    )
    provider_name = models.CharField(max_length=120, blank=True, default="")
    attempt_number = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["attempt_number"]
        constraints = [
            models.UniqueConstraint(fields=["job", "attempt_number"], name="uq_imaging_job_attempt_number"),
        ]

    def __str__(self) -> str:
        return f"{self.job_id}:{self.attempt_number}:{self.provider_name} ({self.status})"
