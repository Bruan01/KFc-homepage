from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class StoreProduct(models.Model):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    STATUS_CHOICES = (
        (DRAFT, "草稿"),
        (ACTIVE, "上架"),
        (ARCHIVED, "下架"),
    )

    id = models.AutoField(primary_key=True)
    slug = models.SlugField(max_length=160, unique=True)
    name = models.CharField(max_length=160)
    summary = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    cover_url = models.TextField(blank=True, default="")
    points_cost = models.PositiveIntegerField(default=0)
    per_user_limit = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    created_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["status", "-updated_at"], name="store_product_status_idx")]


class StoreCode(models.Model):
    AVAILABLE = "available"
    REDEEMED = "redeemed"
    REVOKED = "revoked"
    STATUS_CHOICES = (
        (AVAILABLE, "可兑换"),
        (REDEEMED, "已兑换"),
        (REVOKED, "已撤销"),
    )

    id = models.AutoField(primary_key=True)
    product = models.ForeignKey(StoreProduct, on_delete=models.PROTECT, related_name="codes")
    code_ciphertext = models.TextField()
    code_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=AVAILABLE)
    imported_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "code_digest"], name="uq_store_product_code_digest"),
        ]
        indexes = [
            models.Index(fields=["product", "status"], name="store_code_stock_idx"),
        ]


class StoreRedemption(models.Model):
    FULFILLED = "fulfilled"
    REVOKED = "revoked"
    STATUS_CHOICES = ((FULFILLED, "已发放"), (REVOKED, "已撤销"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="store_redemptions")
    product = models.ForeignKey(StoreProduct, on_delete=models.PROTECT, related_name="redemptions")
    code = models.OneToOneField(StoreCode, on_delete=models.PROTECT, related_name="redemption")
    point_ledger = models.ForeignKey("points.PointLedger", on_delete=models.PROTECT, related_name="store_redemptions")
    points_cost = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=FULFILLED)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
