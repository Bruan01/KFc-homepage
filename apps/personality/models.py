import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def timestamp():
    return timezone.now().isoformat()


THEMES = [(name, name) for name in ("nature", "sunshine", "rational", "romantic")]


class PersonalitySettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=True)
    ai_enabled = models.BooleanField(default=False)
    base_url = models.CharField(max_length=500, blank=True)
    model = models.CharField(max_length=150, blank=True)
    api_key_ciphertext = models.TextField(blank=True)
    timeout_seconds = models.PositiveSmallIntegerField(default=90)
    max_output_tokens = models.PositiveIntegerField(default=8000)
    token_parameter = models.CharField(max_length=30, default="max_tokens")
    provider_check = models.JSONField(default=dict)
    evidence_enabled = models.BooleanField(default=True)
    evidence_api_key_ciphertext = models.TextField(blank=True)
    worker_last_seen_at = models.TextField(blank=True)
    recent_years = models.PositiveSmallIntegerField(default=10)
    min_work_collects = models.PositiveIntegerField(default=2000)
    min_character_collects = models.PositiveIntegerField(default=10)
    per_work_limit = models.PositiveSmallIntegerField(default=5)
    daily_reports_per_user = models.PositiveSmallIntegerField(default=5)
    updated_at = models.TextField(default=timestamp)
    updated_by = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "personality_settings"
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name="personality_settings_one")]


class Character(models.Model):
    source_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=150)
    work_id = models.PositiveIntegerField()
    work_name = models.CharField(max_length=250)
    work_year = models.PositiveSmallIntegerField(null=True, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    image_layout = models.CharField(max_length=16, default="portrait", choices=[("portrait", "图片"), ("cutout", "立绘")])
    source_text = models.TextField(blank=True)
    extra_sources = models.JSONField(default=list)
    evidence_cache = models.JSONField(default=dict)
    source_url = models.URLField(max_length=500)
    source_stats = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default="candidate", choices=[(s, s) for s in ("candidate", "draft", "approved", "excluded")])
    classic_candidate = models.BooleanField(default=False)
    classic = models.BooleanField(default=False)
    theme = models.CharField(max_length=16, choices=THEMES, default="nature")
    # Each dimension requires a level, rationale and an exact source excerpt.
    profile = models.JSONField(default=dict)
    profile_check = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=0)
    reviewed_by = models.CharField(max_length=150, blank=True)
    reviewed_at = models.TextField(blank=True)
    imported_at = models.TextField(default=timestamp)

    class Meta:
        db_table = "personality_characters"
        ordering = ["-classic", "name"]


class CharacterDiscovery(models.Model):
    source_id = models.PositiveIntegerField(unique=True)
    work_id = models.PositiveIntegerField()
    name = models.CharField(max_length=150, blank=True)
    outcome = models.CharField(max_length=20, default="fetching")
    reason = models.CharField(max_length=300, blank=True)
    job_id = models.CharField(max_length=40, blank=True)
    first_seen_at = models.TextField(default=timestamp)
    last_attempt_at = models.TextField(default=timestamp)

    class Meta:
        db_table = "personality_character_discovery"


class CharacterWorkScan(models.Model):
    work_id = models.PositiveIntegerField()
    scope = models.CharField(max_length=64)
    scanned_at = models.TextField(default=timestamp)

    class Meta:
        db_table = "personality_work_scans"
        constraints = [models.UniqueConstraint(fields=["work_id", "scope"], name="one_character_work_scan")]


class Assessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="personality_assessments")
    version = models.CharField(max_length=30, default="xinying-1")
    steps = models.JSONField(default=list)
    step_index = models.PositiveSmallIntegerField(default=0)
    answers = models.JSONField(default=dict)
    ai_consent = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, default="active", choices=[(s, s) for s in ("active", "ready", "queued", "processing", "completed", "failed")])
    # Immutable report snapshot: changes in the character pool cannot reorder it.
    report = models.JSONField(default=dict)
    created_at = models.TextField(default=timestamp)
    updated_at = models.TextField(default=timestamp)

    class Meta:
        db_table = "personality_assessments"
        indexes = [models.Index(fields=["user", "created_at"], name="personality_history_idx")]


class PersonalityJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=[("import", "import"), ("profile", "profile"), ("report", "report"), ("followup", "followup")])
    assessment = models.ForeignKey(Assessment, null=True, blank=True, on_delete=models.CASCADE)
    character = models.ForeignKey(Character, null=True, blank=True, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, default="queued")
    parameters = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    checkpoint = models.JSONField(default=dict)
    phase = models.CharField(max_length=40, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    claim_token = models.CharField(max_length=32, blank=True)
    requested_by = models.CharField(max_length=150)
    error = models.TextField(blank=True)
    started_at = models.TextField(blank=True)
    created_at = models.TextField(default=timestamp)
    updated_at = models.TextField(default=timestamp)

    class Meta:
        db_table = "personality_jobs"
        constraints = [
            models.UniqueConstraint(fields=["assessment"], condition=models.Q(status__in=["queued", "processing"]), name="one_live_personality_report"),
            models.UniqueConstraint(fields=["character"], condition=models.Q(kind="profile", status__in=["queued", "processing"]), name="one_live_character_profile"),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="personality_job_queue")]


class DailyUsage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    day = models.CharField(max_length=10)
    reports = models.PositiveIntegerField(default=0)
    followup_requests = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "personality_daily_usage"
        constraints = [models.UniqueConstraint(fields=["user", "day"], name="personality_daily_user")]


class AnalysisCall(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='analysis_calls')
    job = models.ForeignKey(PersonalityJob, null=True, on_delete=models.SET_NULL)
    stage = models.CharField(max_length=80)
    status = models.CharField(max_length=16, default='running')
    request = models.JSONField(default=dict)
    response = models.JSONField(default=dict)
    usage = models.JSONField(default=dict)
    error = models.CharField(max_length=300, blank=True)
    elapsed_ms = models.PositiveIntegerField(default=0)
    created_at = models.TextField(default=timestamp)
    completed_at = models.TextField(blank=True)

    class Meta:
        db_table = 'personality_analysis_calls'
        ordering = ['created_at']
        indexes = [models.Index(fields=['assessment','created_at'], name='personality_trace_owner')]


class QuestionFeedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE)
    question_id = models.CharField(max_length=80)
    question_version = models.CharField(max_length=30)
    question_text = models.TextField()
    status = models.CharField(max_length=16, default='new', choices=[('new', '待处理'), ('handled', '已处理')])
    handled_by = models.CharField(max_length=150, blank=True)
    created_at = models.TextField(default=timestamp)

    class Meta:
        db_table = 'personality_question_feedback'
        constraints = [models.UniqueConstraint(fields=['assessment', 'question_id'], name='one_question_feedback')]
        indexes = [models.Index(fields=['status', 'created_at'], name='personality_feedback_queue')]


class OperationalAlert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(PersonalityJob, on_delete=models.CASCADE, related_name='operational_alert')
    code = models.CharField(max_length=16, choices=[('stalled', '等待较久'), ('failed', '任务失败')])
    status = models.CharField(max_length=16, default='open', choices=[('open', '待查看'), ('acknowledged', '已知悉'), ('resolved', '已恢复')])
    acknowledged_by = models.CharField(max_length=150, blank=True)
    created_at = models.TextField(default=timestamp)
    resolved_at = models.TextField(blank=True)

    class Meta:
        db_table = 'personality_operational_alerts'
        indexes = [models.Index(fields=['status', 'created_at'], name='personality_alert_queue')]
