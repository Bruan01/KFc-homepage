import uuid

from django.db import models
from django.utils import timezone


def timestamp():
    return timezone.now().isoformat()


DEFAULT_PERSONA = "你是 KFlow 社区助手小 K。用自然、友善、简洁的中文回答，适量使用表情。优先依据社区资料回答，不知道时明确说明，不编造产品功能、活动或官方承诺。"


class AssistantSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    base_url = models.CharField(max_length=500, blank=True, default="")
    api_key_ciphertext = models.TextField(blank=True, default="")
    model = models.CharField(max_length=150, blank=True, default="")
    persona = models.TextField(default=DEFAULT_PERSONA)
    knowledge = models.TextField(blank=True, default="")
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.TextField(default=timestamp)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    worker_last_seen_at = models.TextField(blank=True, default="")

    class Meta:
        db_table = "community_ai_settings"
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name="community_ai_settings_singleton")]


class AssistantReplyJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_key = models.CharField(max_length=80, unique=True)
    post = models.ForeignKey("murmurs.Murmur", on_delete=models.CASCADE, related_name="ai_reply_jobs")
    source_comment = models.ForeignKey("murmurs.MurmurComment", null=True, blank=True, on_delete=models.CASCADE, related_name="ai_request_jobs")
    official = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL, related_name="community_ai_jobs")
    requester_username = models.CharField(max_length=150)
    trigger_excerpt = models.TextField(blank=True, default="")
    result_comment = models.OneToOneField("murmurs.MurmurComment", null=True, blank=True, on_delete=models.SET_NULL, related_name="ai_result_job")
    status = models.CharField(max_length=16, default="queued", choices=[(s, s) for s in ("queued", "processing", "completed", "failed", "skipped")])
    attempts = models.PositiveIntegerField(default=0)
    claim_token = models.CharField(max_length=64, blank=True, default="")
    config_revision = models.PositiveIntegerField(default=0)
    next_attempt_at = models.TextField(blank=True, default="")
    started_at = models.TextField(blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    created_at = models.TextField(default=timestamp)
    updated_at = models.TextField(default=timestamp)

    class Meta:
        db_table = "community_ai_reply_jobs"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "created_at"], name="community_ai_queue_idx")]
