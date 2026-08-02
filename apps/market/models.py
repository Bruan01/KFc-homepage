from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class MarketRound(models.Model):
    DRAFT = "draft"
    OPEN = "open"
    PAUSED = "paused"
    SETTLING = "settling"
    CLOSED = "closed"
    STATUS_CHOICES = (
        (DRAFT, "草稿"),
        (OPEN, "交易中"),
        (PAUSED, "已暂停"),
        (SETTLING, "结算中"),
        (CLOSED, "已结束"),
    )

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=160)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    seed = models.PositiveBigIntegerField(default=1)
    fee_bps = models.PositiveIntegerField(default=200)
    spread_bps = models.PositiveIntegerField(default=300)
    max_order_points = models.PositiveIntegerField(default=100)
    daily_user_stake_limit = models.PositiveIntegerField(default=500)
    daily_user_orders_limit = models.PositiveIntegerField(default=20)
    daily_user_payout_limit = models.PositiveIntegerField(default=1000)
    cooldown_seconds = models.PositiveIntegerField(default=0)
    max_position_shares = models.PositiveIntegerField(default=100)
    max_profit_bps = models.PositiveIntegerField(default=1000)
    bot_initial_cash = models.PositiveIntegerField(default=0)
    bot_cash_balance = models.PositiveIntegerField(default=0)
    bot_max_loss = models.PositiveIntegerField(default=0)
    bot_daily_payout_limit = models.PositiveIntegerField(default=0)
    bot_daily_payout_used = models.PositiveIntegerField(default=0)
    reserved_payout_points = models.PositiveIntegerField(default=0)
    pause_reason = models.TextField(blank=True, default="")
    created_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_at", "-id"]
        indexes = [models.Index(fields=["status", "starts_at", "ends_at"], name="market_round_active_idx")]


class MarketAsset(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    base_price = models.DecimalField(max_digits=12, decimal_places=2, default=10)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code", "id"]


class MarketBotInventory(models.Model):
    round = models.ForeignKey(MarketRound, on_delete=models.CASCADE, related_name="bot_inventory")
    asset = models.ForeignKey(MarketAsset, on_delete=models.PROTECT, related_name="bot_inventory")
    initial_shares = models.PositiveIntegerField(default=0)
    shares_available = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["round", "asset"], name="uq_market_round_asset_inventory")]


class MarketBotDailyUsage(models.Model):
    round = models.ForeignKey(MarketRound, on_delete=models.CASCADE, related_name="bot_daily_usage")
    activity_date = models.DateField()
    payout_points = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["round", "activity_date"], name="uq_market_bot_round_date")]
        indexes = [models.Index(fields=["round", "activity_date"], name="market_bot_usage_date_idx")]


class MarketQuote(models.Model):
    round = models.ForeignKey(MarketRound, on_delete=models.CASCADE, related_name="quotes")
    asset = models.ForeignKey(MarketAsset, on_delete=models.PROTECT, related_name="quotes")
    bucket = models.PositiveBigIntegerField()
    mid_price = models.DecimalField(max_digits=12, decimal_places=2)
    bid_price = models.DecimalField(max_digits=12, decimal_places=2)
    ask_price = models.DecimalField(max_digits=12, decimal_places=2)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["round", "asset", "bucket"], name="uq_market_round_asset_bucket")]
        indexes = [models.Index(fields=["round", "asset", "-bucket"], name="market_quote_latest_idx")]


class MarketPosition(models.Model):
    ACTIVE = "active"
    CLOSED = "closed"
    STATUS_CHOICES = ((ACTIVE, "持仓中"), (CLOSED, "已平仓"))

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="market_positions")
    round = models.ForeignKey(MarketRound, on_delete=models.PROTECT, related_name="positions")
    asset = models.ForeignKey(MarketAsset, on_delete=models.PROTECT, related_name="positions")
    shares = models.PositiveIntegerField(default=0)
    average_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    invested_points = models.PositiveIntegerField(default=0)
    invested_fee_points = models.PositiveIntegerField(default=0)
    reserved_payout_points = models.PositiveIntegerField(default=0)
    realized_points = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "round", "asset"], name="uq_market_user_round_asset")]
        indexes = [models.Index(fields=["user", "round", "status"], name="market_user_round_position_idx")]


class MarketDailyUsage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="market_daily_usage")
    round = models.ForeignKey(MarketRound, on_delete=models.CASCADE, related_name="daily_usage")
    activity_date = models.DateField()
    stake_points = models.PositiveIntegerField(default=0)
    order_count = models.PositiveIntegerField(default=0)
    payout_points = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "round", "activity_date"], name="uq_market_user_round_date")]


class MarketOrder(models.Model):
    BUY = "buy"
    SELL = "sell"
    SIDE_CHOICES = ((BUY, "买入"), (SELL, "卖出"))
    FILLED = "filled"
    REJECTED = "rejected"
    STATUS_CHOICES = ((FILLED, "成交"), (REJECTED, "拒绝"))
    USER = "user"
    SETTLEMENT = "settlement"
    SOURCE_CHOICES = ((USER, "用户下单"), (SETTLEMENT, "轮次结算"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="market_orders")
    round = models.ForeignKey(MarketRound, on_delete=models.PROTECT, related_name="orders")
    asset = models.ForeignKey(MarketAsset, on_delete=models.PROTECT, related_name="orders")
    side = models.CharField(max_length=10, choices=SIDE_CHOICES)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    gross_points = models.PositiveIntegerField()
    fee_points = models.PositiveIntegerField(default=0)
    net_points = models.IntegerField()
    profit_points = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=FILLED)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=USER)
    idempotency_key = models.CharField(max_length=160, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "round", "-created_at"], name="market_user_order_idx")]


class MarketTreasuryLedger(models.Model):
    SEED = "seed"
    BUY_IN = "buy_in"
    SELL_PAYOUT = "sell_payout"
    FEE_BURN = "fee_burn"
    SETTLEMENT = "settlement"
    ADMIN_FUND = "admin_fund"
    EVENT_CHOICES = tuple((value, value) for value in (SEED, ADMIN_FUND, BUY_IN, SELL_PAYOUT, FEE_BURN, SETTLEMENT))

    id = models.AutoField(primary_key=True)
    round = models.ForeignKey(MarketRound, on_delete=models.PROTECT, related_name="treasury_ledger")
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    delta = models.IntegerField(default=0)
    balance_after = models.IntegerField()
    fee_points = models.PositiveIntegerField(default=0)
    reference_id = models.CharField(max_length=160, blank=True, default="")
    idempotency_key = models.CharField(max_length=180, unique=True)
    created_by = models.CharField(max_length=150, default="system")
    created_at = models.DateTimeField(auto_now_add=True)


class MarketAdminAudit(models.Model):
    round = models.ForeignKey(MarketRound, on_delete=models.SET_NULL, null=True, blank=True, related_name="admin_audits")
    action = models.CharField(max_length=50)
    operator = models.CharField(max_length=150)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["round", "-created_at"], name="market_audit_round_idx")]
