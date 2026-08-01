"""Django ORM models backed by the legacy download tables."""
from django.conf import settings
from django.db import models


class DownloadRequest(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, db_column="user_id", on_delete=models.DO_NOTHING, related_name="download_requests")
    product = models.ForeignKey("catalog.Product", db_column="product_id", on_delete=models.DO_NOTHING, related_name="download_requests")
    reason = models.TextField(blank=True, default="")
    status = models.TextField(default="pending")
    review_note = models.TextField(blank=True, default="")
    created_at = models.TextField()
    reviewed_at = models.TextField(null=True, blank=True)
    reviewed_by = models.TextField(null=True, blank=True)
    consumed_at = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "download_requests"
        managed = True


class DownloadEntitlement(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, db_column="user_id", on_delete=models.DO_NOTHING, related_name="download_entitlements")
    product = models.ForeignKey("catalog.Product", db_column="product_id", on_delete=models.DO_NOTHING, related_name="download_entitlements")
    source = models.TextField()
    point_ledger = models.ForeignKey(
        "points.PointLedger",
        db_column="point_ledger_id",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="download_entitlements",
    )
    cost = models.IntegerField(default=0)
    remaining_count = models.IntegerField(default=1)
    idempotency_key = models.TextField(unique=True)
    created_at = models.TextField()
    expires_at = models.TextField(null=True, blank=True)
    consumed_at = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "download_entitlements"
        managed = True


class Download(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey("catalog.Product", db_column="product_id", on_delete=models.DO_NOTHING, related_name="downloads")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="user_id",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="downloads",
    )
    request = models.ForeignKey(
        DownloadRequest,
        db_column="request_id",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="downloads",
    )
    entitlement = models.ForeignKey(
        DownloadEntitlement,
        db_column="entitlement_id",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="downloads",
    )
    downloaded_at = models.TextField()
    ip = models.TextField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "downloads"
        managed = True


class UploadSession(models.Model):
    id = models.AutoField(primary_key=True)
    upload_id = models.TextField(unique=True)
    product_id = models.IntegerField()
    username = models.TextField()
    level = models.IntegerField()
    original = models.TextField()
    size = models.BigIntegerField()
    count = models.IntegerField()
    platform = models.TextField()
    architecture = models.TextField()
    expires_at = models.FloatField()
    written = models.BigIntegerField(default=0)
    expected_sha256 = models.TextField(null=True, blank=True)
    created_at = models.TextField()

    class Meta:
        db_table = "django_upload_sessions"
        managed = True
