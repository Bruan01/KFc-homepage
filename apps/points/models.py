"""Django ORM models backed by the legacy points tables."""
from django.conf import settings
from django.db import models


class PointAccount(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        db_column="user_id",
        primary_key=True,
        on_delete=models.DO_NOTHING,
        related_name="point_account",
    )
    balance = models.IntegerField(default=0)
    total_earned = models.IntegerField(default=0)
    total_spent = models.IntegerField(default=0)
    contribution_score = models.IntegerField(default=0)
    reputation_level = models.IntegerField(default=0)
    consecutive_active_days = models.IntegerField(default=0)
    last_active_date = models.TextField(null=True, blank=True)
    status = models.TextField(default="active")
    updated_at = models.TextField()

    class Meta:
        db_table = "point_accounts"
        managed = True


class PointLedger(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, db_column="user_id", on_delete=models.DO_NOTHING, related_name="point_ledger")
    event_type = models.TextField()
    delta = models.IntegerField()
    balance_after = models.IntegerField()
    contribution_delta = models.IntegerField(default=0)
    reference_type = models.TextField(blank=True, default="")
    reference_id = models.TextField(blank=True, default="")
    idempotency_key = models.TextField(unique=True)
    description = models.TextField(blank=True, default="")
    status = models.TextField(default="settled")
    available_at = models.TextField(null=True, blank=True)
    created_by = models.TextField(default="system")
    created_at = models.TextField()

    class Meta:
        db_table = "point_ledger"
        managed = True


class UserDailyActivity(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, db_column="user_id", on_delete=models.DO_NOTHING, related_name="daily_activity")
    activity_date = models.TextField()
    created_at = models.TextField()

    class Meta:
        db_table = "user_daily_activity"
        managed = True
        constraints = [
            models.UniqueConstraint(fields=["user", "activity_date"], name="uq_daily_activity_user_date"),
        ]
