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


class StoreListing(models.Model):
    """A user-created listing on the kflowstore creator shelf."""

    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_REJECTED = "rejected"
    STATUS_OFF_SHELF = "off_shelf"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "草稿"),
        (STATUS_PENDING, "待审核"),
        (STATUS_ACTIVE, "在售"),
        (STATUS_REJECTED, "已驳回"),
        (STATUS_OFF_SHELF, "已下架"),
    )

    DELIVERABLE_TEXT = "text"
    DELIVERABLE_CODE = "code"
    DELIVERABLE_LINK = "link"
    DELIVERABLE_CHOICES = (
        (DELIVERABLE_TEXT, "文本说明"),
        (DELIVERABLE_CODE, "兑换码"),
        (DELIVERABLE_LINK, "外部链接"),
    )

    id = models.AutoField(primary_key=True)
    seller_username = models.CharField(max_length=150)
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=300, blank=True, default="")
    description = models.TextField(blank=True, default="")
    cover_url = models.CharField(max_length=500, blank=True, default="")
    price_points = models.PositiveIntegerField(default=10)
    stock = models.PositiveIntegerField(default=0)  # 0 = unlimited (text/link)
    per_user_limit = models.PositiveIntegerField(default=1)
    deliverable_type = models.CharField(max_length=16, choices=DELIVERABLE_CHOICES, default=DELIVERABLE_TEXT)
    deliverable_text = models.TextField(blank=True, default="")  # text payload or code template
    deliverable_codes = models.TextField(blank=True, default="")  # newline-separated codes
    deliverable_link = models.URLField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    review_reason = models.TextField(blank=True, default="")
    reviewed_by = models.CharField(max_length=150, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    sold_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "store_listings"
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["status", "-updated_at"], name="store_listing_status_idx")]


class ListingRedemption(models.Model):
    """A completed points purchase of a creator listing (idempotent)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(StoreListing, on_delete=models.PROTECT, related_name="redemptions", db_column="listing_id")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="listing_redemptions")
    buyer_username = models.CharField(max_length=150)
    seller_username = models.CharField(max_length=150)
    points_paid = models.PositiveIntegerField(default=0)
    seller_earning = models.PositiveIntegerField(default=0)
    delivered_payload = models.TextField()  # snapshot of what was delivered
    buyer_ledger_id = models.IntegerField(default=0)
    seller_ledger_id = models.IntegerField(default=0)
    idempotency_key = models.CharField(max_length=160, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_redemptions"
        ordering = ["-created_at"]
