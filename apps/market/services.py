from __future__ import annotations

import hashlib
import math
import uuid
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from http import HTTPStatus

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.points.services import PointsError, account_payload, apply_ledger
from .models import (
    MarketAsset,
    MarketBotDailyUsage,
    MarketBotInventory,
    MarketAdminAudit,
    MarketDailyUsage,
    MarketOrder,
    MarketPosition,
    MarketQuote,
    MarketRound,
    MarketTreasuryLedger,
)

MONEY_QUANTUM = Decimal("0.01")


class MarketError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = int(status)


def _now():
    return timezone.now()


def _ceil_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)


def _floor_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_DOWN)


def _points_ceil(value: Decimal) -> int:
    return max(0, int(value.to_integral_value(rounding=ROUND_CEILING)))


def _points_floor(value: Decimal) -> int:
    return max(0, int(value.to_integral_value(rounding=ROUND_DOWN)))


def _idempotency_key(value) -> str:
    key = str(value or "").strip()
    if len(key) < 8 or len(key) > 160:
        raise MarketError("valid idempotency key required")
    return key


def current_round(*, at=None):
    now = at or _now()
    return MarketRound.objects.filter(
        status__in=[MarketRound.OPEN, MarketRound.PAUSED],
        starts_at__lte=now,
        ends_at__gt=now,
    ).order_by("starts_at", "id").first()


def _require_open(round_row: MarketRound) -> None:
    now = _now()
    if round_row.status == MarketRound.PAUSED:
        raise MarketError("market round is paused", HTTPStatus.CONFLICT)
    if round_row.status != MarketRound.OPEN or not (round_row.starts_at <= now < round_row.ends_at):
        raise MarketError("market round is not open", HTTPStatus.CONFLICT)


def _quote_values(round_row: MarketRound, asset: MarketAsset, bucket: int):
    digest = hashlib.sha256(f"{round_row.seed}:{asset.code}:{bucket}".encode("utf-8")).digest()
    movement = int.from_bytes(digest[:8], "big") % 2001 - 1000
    base = Decimal(asset.base_price)
    mid = _floor_money(max(MONEY_QUANTUM, base * Decimal(10000 + movement) / Decimal(10000)))
    spread = max(0, min(2000, int(round_row.spread_bps)))
    bid = _floor_money(max(MONEY_QUANTUM, mid * Decimal(10000 - spread) / Decimal(10000)))
    ask = _ceil_money(max(bid, mid * Decimal(10000 + spread) / Decimal(10000)))
    return mid, bid, ask


def get_quote(round_row: MarketRound, asset: MarketAsset, *, at=None) -> MarketQuote:
    at = at or _now()
    bucket = int(at.timestamp() // 60)
    mid, bid, ask = _quote_values(round_row, asset, bucket)
    try:
        quote, _ = MarketQuote.objects.get_or_create(
            round=round_row,
            asset=asset,
            bucket=bucket,
            defaults={"mid_price": mid, "bid_price": bid, "ask_price": ask},
        )
    except IntegrityError:
        quote = MarketQuote.objects.get(round=round_row, asset=asset, bucket=bucket)
    return quote


def quote_payload(quote: MarketQuote) -> dict:
    return {
        "assetId": quote.asset_id,
        "code": quote.asset.code,
        "name": quote.asset.name,
        "bucket": quote.bucket,
        "midPrice": str(quote.mid_price),
        "bidPrice": str(quote.bid_price),
        "askPrice": str(quote.ask_price),
        "generatedAt": quote.generated_at.isoformat(),
    }


def round_payload(round_row: MarketRound | None) -> dict | None:
    if not round_row:
        return None
    daily_bot_usage = MarketBotDailyUsage.objects.filter(
        round=round_row,
        activity_date=timezone.localdate(),
    ).values_list("payout_points", flat=True).first() or 0
    return {
        "id": round_row.pk,
        "name": round_row.name,
        "status": round_row.status,
        "startsAt": round_row.starts_at.isoformat(),
        "endsAt": round_row.ends_at.isoformat(),
        "feeBps": round_row.fee_bps,
        "spreadBps": round_row.spread_bps,
        "maxOrderPoints": round_row.max_order_points,
        "dailyUserStakeLimit": round_row.daily_user_stake_limit,
        "dailyUserOrdersLimit": round_row.daily_user_orders_limit,
        "dailyUserPayoutLimit": round_row.daily_user_payout_limit,
        "cooldownSeconds": round_row.cooldown_seconds,
        "maxPositionShares": round_row.max_position_shares,
        "maxProfitBps": round_row.max_profit_bps,
        "botInitialCash": round_row.bot_initial_cash,
        "botCashBalance": round_row.bot_cash_balance,
        "botMaxLoss": round_row.bot_max_loss,
        "botDailyPayoutLimit": round_row.bot_daily_payout_limit,
        "botDailyPayoutUsed": daily_bot_usage,
        "botPayoutUsedTotal": round_row.bot_daily_payout_used,
        "reservedPayoutPoints": round_row.reserved_payout_points,
        "pauseReason": round_row.pause_reason,
    }


def _fee_points(gross: int, round_row: MarketRound) -> int:
    if gross <= 0 or round_row.fee_bps <= 0:
        return 0
    return max(1, math.ceil(gross * round_row.fee_bps / 10000))


def _max_reservation(gross: int, round_row: MarketRound) -> int:
    profit = math.ceil(gross * round_row.max_profit_bps / 10000)
    return gross + profit


def _treasury_event(*, round_row: MarketRound, event_type: str, delta: int, fee_points: int = 0, reference_id: str = "", idempotency_key: str, created_by: str = "system"):
    if MarketTreasuryLedger.objects.filter(idempotency_key=idempotency_key).exists():
        return
    new_balance = int(round_row.bot_cash_balance) + int(delta)
    if new_balance < 0:
        raise MarketError("market bot treasury is insufficient", HTTPStatus.CONFLICT)
    round_row.bot_cash_balance = new_balance
    round_row.save(update_fields=["bot_cash_balance", "updated_at"])
    MarketTreasuryLedger.objects.create(
        round=round_row,
        event_type=event_type,
        delta=delta,
        balance_after=new_balance,
        fee_points=fee_points,
        reference_id=str(reference_id or ""),
        idempotency_key=idempotency_key,
        created_by=created_by,
    )


def _daily_usage(user, round_row, *, activity_date=None) -> MarketDailyUsage:
    activity_date = activity_date or timezone.localdate()
    usage, _ = MarketDailyUsage.objects.select_for_update().get_or_create(
        user=user,
        round=round_row,
        activity_date=activity_date,
    )
    return usage


def _bot_daily_usage(round_row: MarketRound, *, activity_date=None) -> MarketBotDailyUsage:
    usage, _ = MarketBotDailyUsage.objects.select_for_update().get_or_create(
        round=round_row,
        activity_date=activity_date or timezone.localdate(),
    )
    return usage


def _check_cooldown(*, user, round_row: MarketRound) -> None:
    if not round_row.cooldown_seconds:
        return
    last_order = MarketOrder.objects.filter(
        user=user,
        round=round_row,
        source=MarketOrder.USER,
    ).order_by("-created_at").first()
    if last_order and (_now() - last_order.created_at).total_seconds() < round_row.cooldown_seconds:
        raise MarketError("trade cooldown is active", HTTPStatus.CONFLICT)


def _points_error(exc: PointsError) -> MarketError:
    return MarketError(exc.message, exc.status)


def _order_payload(order: MarketOrder) -> dict:
    return {
        "id": str(order.pk),
        "roundId": order.round_id,
        "assetId": order.asset_id,
        "assetCode": order.asset.code,
        "side": order.side,
        "quantity": order.quantity,
        "unitPrice": str(order.unit_price),
        "grossPoints": order.gross_points,
        "feePoints": order.fee_points,
        "netPoints": order.net_points,
        "status": order.status,
        "source": order.source,
        "createdAt": order.created_at.isoformat(),
    }


def place_order(*, user, asset_id: int, side: str, quantity: int, idempotency_key: str):
    key = _idempotency_key(idempotency_key)
    if side not in {MarketOrder.BUY, MarketOrder.SELL}:
        raise MarketError("side must be buy or sell")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise MarketError("quantity must be an integer") from exc
    if quantity < 1 or quantity > 100000:
        raise MarketError("invalid order quantity")

    with transaction.atomic():
        existing = MarketOrder.objects.select_related("round", "asset").filter(idempotency_key=key).first()
        if existing:
            if existing.user_id != user.pk:
                raise MarketError("idempotency key conflict", HTTPStatus.CONFLICT)
            return existing, account_payload(user), False

        active_round = current_round()
        round_row = MarketRound.objects.select_for_update().filter(pk=active_round.pk if active_round else -1).first()
        if not round_row:
            raise MarketError("no open market round", HTTPStatus.CONFLICT)
        # The round lock serializes concurrent requests for the same active
        # market. Re-read the unique key after acquiring it so a retry that
        # started before the first request committed becomes a clean replay.
        existing = MarketOrder.objects.select_related("round", "asset").filter(idempotency_key=key).first()
        if existing:
            if existing.user_id != user.pk:
                raise MarketError("idempotency key conflict", HTTPStatus.CONFLICT)
            return existing, account_payload(user), False
        _require_open(round_row)
        asset = MarketAsset.objects.select_for_update().filter(pk=asset_id, active=True).first()
        if not asset:
            raise MarketError("market asset not found", HTTPStatus.NOT_FOUND)
        inventory = MarketBotInventory.objects.select_for_update().filter(round=round_row, asset=asset).first()
        if not inventory:
            raise MarketError("asset liquidity is unavailable", HTTPStatus.CONFLICT)
        quote = get_quote(round_row, asset)
        usage = _daily_usage(user, round_row)
        _check_cooldown(user=user, round_row=round_row)
        if usage.order_count >= round_row.daily_user_orders_limit:
            raise MarketError("daily order limit reached", HTTPStatus.CONFLICT)

        if side == MarketOrder.BUY:
            if inventory.shares_available < quantity:
                raise MarketError("market maker inventory is insufficient", HTTPStatus.CONFLICT)
            price = quote.ask_price
            gross = _points_ceil(price * quantity)
            fee = _fee_points(gross, round_row)
            total = gross + fee
            if total > round_row.max_order_points:
                raise MarketError("order exceeds max order points", HTTPStatus.CONFLICT)
            if usage.stake_points + total > round_row.daily_user_stake_limit:
                raise MarketError("daily stake limit reached", HTTPStatus.CONFLICT)
            position, _ = MarketPosition.objects.select_for_update().get_or_create(user=user, round=round_row, asset=asset)
            if position.shares + quantity > round_row.max_position_shares:
                raise MarketError("position share limit reached", HTTPStatus.CONFLICT)
            reservation = _max_reservation(gross, round_row)
            new_cash = round_row.bot_cash_balance + gross
            if new_cash - (round_row.reserved_payout_points + reservation) < 0:
                raise MarketError("market maker payout reserve is insufficient", HTTPStatus.CONFLICT)
            try:
                ledger, _ = apply_ledger(
                    user=user,
                    event_type="market_buy",
                    points_delta=-total,
                    idempotency_key=f"market_order:{key}",
                    description=f"K 股市买入 {asset.code} × {quantity}",
                    reference_type="market_order",
                    reference_id=key,
                )
            except PointsError as exc:
                raise _points_error(exc) from exc
            position.shares += quantity
            position.invested_points += gross
            position.reserved_payout_points += reservation
            position.average_cost = _floor_money(Decimal(position.invested_points) / Decimal(position.shares))
            position.status = MarketPosition.ACTIVE
            position.save(update_fields=["shares", "invested_points", "reserved_payout_points", "average_cost", "status", "updated_at"])
            inventory.shares_available -= quantity
            inventory.save(update_fields=["shares_available", "updated_at"])
            round_row.reserved_payout_points += reservation
            round_row.save(update_fields=["reserved_payout_points", "updated_at"])
            _treasury_event(round_row=round_row, event_type=MarketTreasuryLedger.BUY_IN, delta=gross, fee_points=fee, reference_id=key, idempotency_key=f"market_treasury:{key}")
            usage.stake_points += total
            usage.order_count += 1
            usage.save(update_fields=["stake_points", "order_count", "updated_at"])
            order = MarketOrder.objects.create(user=user, round=round_row, asset=asset, side=side, quantity=quantity, unit_price=price, gross_points=gross, fee_points=fee, net_points=-total, idempotency_key=key)
        else:
            position = MarketPosition.objects.select_for_update().filter(user=user, round=round_row, asset=asset, status=MarketPosition.ACTIVE).first()
            if not position or position.shares < quantity:
                raise MarketError("insufficient position shares", HTTPStatus.CONFLICT)
            price = quote.bid_price
            released = position.reserved_payout_points if quantity == position.shares else math.ceil(position.reserved_payout_points * quantity / position.shares)
            if released < 1:
                raise MarketError("position payout reserve is unavailable", HTTPStatus.CONFLICT)
            raw_gross = _points_floor(price * quantity)
            # max_profit_bps is a hard cap, not merely a pre-check. Once the
            # cap is reached, the user receives the reserved maximum and the
            # remaining reserve is released back to the round.
            gross = min(raw_gross, released)
            fee = _fee_points(gross, round_row)
            payout = max(0, gross - fee)
            if usage.payout_points + payout > round_row.daily_user_payout_limit:
                raise MarketError("daily payout limit reached", HTTPStatus.CONFLICT)
            bot_usage = _bot_daily_usage(round_row)
            if bot_usage.payout_points + payout > round_row.bot_daily_payout_limit:
                raise MarketError("market maker daily payout limit reached", HTTPStatus.CONFLICT)
            new_reserved = round_row.reserved_payout_points - released
            new_cash = round_row.bot_cash_balance - payout
            if new_reserved < 0 or new_cash < 0 or new_cash < new_reserved:
                raise MarketError("market maker cash is insufficient", HTTPStatus.CONFLICT)
            if round_row.bot_initial_cash and new_cash < max(0, round_row.bot_initial_cash - round_row.bot_max_loss):
                raise MarketError("market maker loss limit reached", HTTPStatus.CONFLICT)
            try:
                ledger, _ = apply_ledger(
                    user=user,
                    event_type="market_sell",
                    points_delta=payout,
                    idempotency_key=f"market_order:{key}",
                    description=f"K 股市卖出 {asset.code} × {quantity}",
                    reference_type="market_order",
                    reference_id=key,
                )
            except PointsError as exc:
                raise _points_error(exc) from exc
            invested_release = math.floor(position.invested_points * quantity / position.shares)
            position.shares -= quantity
            position.invested_points -= invested_release
            position.reserved_payout_points -= released
            position.realized_points += payout - invested_release
            if position.shares == 0:
                position.status = MarketPosition.CLOSED
                position.average_cost = Decimal("0")
            else:
                position.average_cost = _floor_money(Decimal(position.invested_points) / Decimal(position.shares))
            position.save(update_fields=["shares", "invested_points", "reserved_payout_points", "realized_points", "status", "average_cost", "updated_at"])
            inventory.shares_available += quantity
            inventory.save(update_fields=["shares_available", "updated_at"])
            round_row.reserved_payout_points = new_reserved
            round_row.bot_daily_payout_used += payout
            round_row.save(update_fields=["reserved_payout_points", "bot_daily_payout_used", "updated_at"])
            bot_usage.payout_points += payout
            bot_usage.save(update_fields=["payout_points", "updated_at"])
            _treasury_event(round_row=round_row, event_type=MarketTreasuryLedger.SELL_PAYOUT, delta=-payout, fee_points=fee, reference_id=key, idempotency_key=f"market_treasury:{key}")
            usage.payout_points += payout
            usage.order_count += 1
            usage.save(update_fields=["payout_points", "order_count", "updated_at"])
            execution_price = _floor_money(Decimal(gross) / Decimal(quantity)) if gross else Decimal("0")
            order = MarketOrder.objects.create(user=user, round=round_row, asset=asset, side=side, quantity=quantity, unit_price=execution_price, gross_points=gross, fee_points=fee, net_points=payout, source=MarketOrder.USER, idempotency_key=key)
        return order, account_payload(user), True


def portfolio_payload(user, round_row):
    positions = MarketPosition.objects.filter(user=user, round=round_row, status=MarketPosition.ACTIVE).select_related("asset")
    items = []
    for position in positions:
        quote = get_quote(round_row, position.asset)
        mark = _points_floor(quote.bid_price * position.shares)
        items.append({
            "id": position.pk,
            "assetId": position.asset_id,
            "code": position.asset.code,
            "name": position.asset.name,
            "shares": position.shares,
            "averageCost": str(position.average_cost),
            "investedPoints": position.invested_points,
            "markValue": mark,
            "reservedPayoutPoints": position.reserved_payout_points,
            "realizedPoints": position.realized_points,
        })
    return items


@transaction.atomic
def create_round(*, payload: dict, created_by: str) -> MarketRound:
    from django.utils.dateparse import parse_datetime

    name = str(payload.get("name") or "").strip()
    starts_at = parse_datetime(str(payload.get("startsAt") or ""))
    ends_at = parse_datetime(str(payload.get("endsAt") or ""))
    if not name or not starts_at or not ends_at:
        raise MarketError("name, startsAt and endsAt are required")
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at)
    if timezone.is_naive(ends_at):
        ends_at = timezone.make_aware(ends_at)
    if starts_at >= ends_at:
        raise MarketError("startsAt must be before endsAt")
    integer_fields = {
        "seed": 1, "feeBps": 200, "spreadBps": 300, "maxOrderPoints": 100,
        "dailyUserStakeLimit": 500, "dailyUserOrdersLimit": 20, "dailyUserPayoutLimit": 1000,
        "cooldownSeconds": 0, "maxPositionShares": 100, "maxProfitBps": 1000, "botInitialCash": 0,
        "botMaxLoss": 0, "botDailyPayoutLimit": 0,
    }
    values = {}
    for key, default in integer_fields.items():
        try:
            values[key] = int(payload.get(key, default))
        except (TypeError, ValueError) as exc:
            raise MarketError(f"invalid market setting: {key}") from exc
        if values[key] < 0:
            raise MarketError(f"market setting must be non-negative: {key}")
    if values["maxOrderPoints"] < 1 or values["dailyUserStakeLimit"] < 1 or values["dailyUserOrdersLimit"] < 1 or values["dailyUserPayoutLimit"] < 1 or values["maxPositionShares"] < 1:
        raise MarketError("market limits must be positive")
    if values["feeBps"] > 10000 or values["spreadBps"] > 2000 or values["maxProfitBps"] > 100000:
        raise MarketError("market rate setting is out of range")
    if values["botDailyPayoutLimit"] == 0:
        values["botDailyPayoutLimit"] = values["botInitialCash"]
    if values["botMaxLoss"] == 0:
        values["botMaxLoss"] = values["botInitialCash"]
    if values["botMaxLoss"] > values["botInitialCash"]:
        raise MarketError("botMaxLoss cannot exceed botInitialCash")
    status = str(payload.get("status") or MarketRound.DRAFT)
    if status not in {MarketRound.DRAFT, MarketRound.OPEN, MarketRound.PAUSED}:
        raise MarketError("invalid round status")
    round_row = MarketRound.objects.create(
        name=name, status=status, starts_at=starts_at, ends_at=ends_at, created_by=created_by,
        fee_bps=values["feeBps"], spread_bps=values["spreadBps"], max_order_points=values["maxOrderPoints"],
        daily_user_stake_limit=values["dailyUserStakeLimit"], daily_user_orders_limit=values["dailyUserOrdersLimit"],
        daily_user_payout_limit=values["dailyUserPayoutLimit"], max_position_shares=values["maxPositionShares"],
        cooldown_seconds=values["cooldownSeconds"],
        max_profit_bps=values["maxProfitBps"], seed=values["seed"], bot_initial_cash=values["botInitialCash"],
        bot_cash_balance=values["botInitialCash"], bot_max_loss=values["botMaxLoss"], bot_daily_payout_limit=values["botDailyPayoutLimit"],
    )
    if round_row.bot_initial_cash:
        MarketTreasuryLedger.objects.create(round=round_row, event_type=MarketTreasuryLedger.SEED, delta=round_row.bot_initial_cash, balance_after=round_row.bot_initial_cash, reference_id=str(round_row.pk), idempotency_key=f"market_seed:{round_row.pk}", created_by=created_by)
    MarketAdminAudit.objects.create(round=round_row, action="round_created", operator=created_by, details={"name": round_row.name, "status": round_row.status})
    return round_row


def fund_round(*, round_id: int, amount: int, operator: str, idempotency_key: str | None = None):
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise MarketError("positive amount required") from exc
    if amount < 1:
        raise MarketError("positive amount required")
    key = _idempotency_key(idempotency_key or f"market-admin-fund:{uuid.uuid4()}")
    with transaction.atomic():
        existing = MarketTreasuryLedger.objects.filter(idempotency_key=key).first()
        if existing:
            return existing.round, False
        round_row = MarketRound.objects.select_for_update().filter(pk=round_id).first()
        if not round_row:
            raise MarketError("market round not found", HTTPStatus.NOT_FOUND)
        round_row.bot_cash_balance += amount
        round_row.bot_initial_cash += amount
        round_row.bot_max_loss += amount
        round_row.bot_daily_payout_limit += amount
        round_row.save(update_fields=["bot_cash_balance", "bot_initial_cash", "bot_max_loss", "bot_daily_payout_limit", "updated_at"])
        MarketTreasuryLedger.objects.create(
            round=round_row,
            event_type=MarketTreasuryLedger.ADMIN_FUND,
            delta=amount,
            balance_after=round_row.bot_cash_balance,
            reference_id=str(round_id),
            idempotency_key=key,
            created_by=operator,
        )
        MarketAdminAudit.objects.create(round=round_row, action="fund_round", operator=operator, details={"amount": amount, "idempotencyKey": key})
        return round_row, True


def configure_inventory(*, round_id: int, asset_id: int, shares: int, operator: str = "system"):
    try:
        shares = int(shares)
    except (TypeError, ValueError) as exc:
        raise MarketError("positive shares required") from exc
    if shares < 1:
        raise MarketError("positive shares required")
    with transaction.atomic():
        round_row = MarketRound.objects.select_for_update().filter(pk=round_id).first()
        asset = MarketAsset.objects.select_for_update().filter(pk=asset_id, active=True).first()
        if not round_row or not asset:
            raise MarketError("round or asset not found", HTTPStatus.NOT_FOUND)
        if round_row.status in {MarketRound.SETTLING, MarketRound.CLOSED}:
            raise MarketError("cannot configure inventory after round settlement", HTTPStatus.CONFLICT)
        inventory, created = MarketBotInventory.objects.select_for_update().get_or_create(
            round=round_row,
            asset=asset,
            defaults={"initial_shares": shares, "shares_available": shares},
        )
        if not created and MarketOrder.objects.filter(round=round_row, asset=asset).exists():
            raise MarketError("cannot change inventory after trades", HTTPStatus.CONFLICT)
        inventory.initial_shares = shares
        inventory.shares_available = shares
        inventory.save(update_fields=["initial_shares", "shares_available", "updated_at"])
        MarketAdminAudit.objects.create(round=round_row, action="configure_inventory", operator=operator, details={"assetId": asset.pk, "shares": shares})
        return inventory


def create_asset(*, payload: dict, operator: str = "system") -> MarketAsset:
    code = str(payload.get("code") or "").strip().upper()
    name = str(payload.get("name") or "").strip()
    if not code or not name:
        raise MarketError("code and name are required")
    try:
        base_price = Decimal(str(payload.get("basePrice", "10")))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise MarketError("invalid base price") from exc
    if base_price <= 0:
        raise MarketError("basePrice must be positive")
    if len(code) > 20:
        raise MarketError("asset code is too long")
    try:
        with transaction.atomic():
            asset = MarketAsset.objects.create(
                code=code,
                name=name,
                description=str(payload.get("description") or "").strip(),
                base_price=base_price,
                active=bool(payload.get("active", True)),
            )
            MarketAdminAudit.objects.create(action="create_asset", operator=operator, details={"assetId": asset.pk, "code": asset.code})
        return asset
    except IntegrityError as exc:
        raise MarketError("asset code already exists", HTTPStatus.CONFLICT) from exc


@transaction.atomic
def update_asset(*, asset_id: int, payload: dict, operator: str = "system") -> MarketAsset:
    asset = MarketAsset.objects.filter(pk=asset_id).first()
    if not asset:
        raise MarketError("market asset not found", HTTPStatus.NOT_FOUND)
    if "name" in payload:
        asset.name = str(payload["name"] or "").strip()
    if "description" in payload:
        asset.description = str(payload["description"] or "").strip()
    if "active" in payload:
        asset.active = bool(payload["active"])
    if not asset.name:
        raise MarketError("asset name is required")
    asset.save(update_fields=["name", "description", "active"])
    MarketAdminAudit.objects.create(action="update_asset", operator=operator, details={"assetId": asset.pk, "active": asset.active})
    return asset


def control_round(*, round_id: int, action: str, operator: str):
    action = str(action or "").strip().lower()
    if action == "settle":
        return settle_round(round_id, operator=operator)
    with transaction.atomic():
        round_row = MarketRound.objects.select_for_update().filter(pk=round_id).first()
        if not round_row:
            raise MarketError("market round not found", HTTPStatus.NOT_FOUND)
        if action == "pause":
            if round_row.status not in {MarketRound.OPEN, MarketRound.PAUSED}:
                raise MarketError("only an open round can be paused", HTTPStatus.CONFLICT)
            round_row.status = MarketRound.PAUSED
            round_row.pause_reason = "管理员暂停"
        elif action == "resume":
            if round_row.status != MarketRound.PAUSED:
                raise MarketError("only a paused round can be resumed", HTTPStatus.CONFLICT)
            if not (round_row.starts_at <= _now() < round_row.ends_at):
                raise MarketError("round is outside its trading window", HTTPStatus.CONFLICT)
            round_row.status = MarketRound.OPEN
            round_row.pause_reason = ""
        else:
            raise MarketError("action must be pause, resume or settle")
        round_row.save(update_fields=["status", "pause_reason", "updated_at"])
        MarketAdminAudit.objects.create(round=round_row, action=f"{action}_round", operator=operator, details={"reason": round_row.pause_reason})
        return round_row


def settle_round(round_id: int, *, operator: str) -> MarketRound:
    with transaction.atomic():
        round_row = MarketRound.objects.select_for_update().filter(pk=round_id).first()
        if not round_row:
            raise MarketError("market round not found", HTTPStatus.NOT_FOUND)
        if round_row.status == MarketRound.CLOSED:
            return round_row
        if round_row.status == MarketRound.DRAFT:
            raise MarketError("draft market round cannot be settled", HTTPStatus.CONFLICT)
        round_row.status = MarketRound.SETTLING
        round_row.save(update_fields=["status", "updated_at"])
        positions = list(MarketPosition.objects.select_for_update().filter(round=round_row, status=MarketPosition.ACTIVE).select_related("user", "asset"))
        settlement_date = timezone.localtime(round_row.ends_at).date()
        for position in positions:
            position_shares = position.shares
            inventory = MarketBotInventory.objects.select_for_update().filter(round=round_row, asset=position.asset).first()
            if not inventory:
                raise MarketError("asset liquidity is unavailable for settlement", HTTPStatus.CONFLICT)
            quote = get_quote(round_row, position.asset, at=round_row.ends_at)
            release = position.reserved_payout_points
            if release < 1 or round_row.reserved_payout_points < release:
                raise MarketError("market payout reserve is inconsistent", HTTPStatus.CONFLICT)
            raw_gross = _points_floor(quote.bid_price * position_shares)
            gross = min(raw_gross, release)
            fee = _fee_points(gross, round_row)
            payout = max(0, gross - fee)
            user_usage = _daily_usage(position.user, round_row, activity_date=settlement_date)
            if user_usage.payout_points + payout > round_row.daily_user_payout_limit:
                raise MarketError("daily payout limit reached during settlement", HTTPStatus.CONFLICT)
            bot_usage = _bot_daily_usage(round_row, activity_date=settlement_date)
            if bot_usage.payout_points + payout > round_row.bot_daily_payout_limit:
                raise MarketError("market maker daily payout limit reached during settlement", HTTPStatus.CONFLICT)
            new_reserved = round_row.reserved_payout_points - release
            new_cash = round_row.bot_cash_balance - payout
            if new_cash < 0 or new_cash < new_reserved:
                raise MarketError("market round cannot settle within bot reserve", HTTPStatus.CONFLICT)
            if round_row.bot_initial_cash and new_cash < max(0, round_row.bot_initial_cash - round_row.bot_max_loss):
                raise MarketError("market maker loss limit reached", HTTPStatus.CONFLICT)
            try:
                apply_ledger(user=position.user, event_type="market_settlement", points_delta=payout, idempotency_key=f"market_settlement:{round_row.pk}:{position.pk}", description=f"K 股市轮次结算：{position.asset.code}", reference_type="market_round", reference_id=round_row.pk, allow_frozen=True)
            except PointsError as exc:
                raise _points_error(exc) from exc
            _treasury_event(round_row=round_row, event_type=MarketTreasuryLedger.SETTLEMENT, delta=-payout, fee_points=fee, reference_id=str(position.pk), idempotency_key=f"market_treasury:settlement:{round_row.pk}:{position.pk}", created_by=operator)
            round_row.reserved_payout_points = new_reserved
            round_row.bot_daily_payout_used += payout
            round_row.save(update_fields=["reserved_payout_points", "bot_daily_payout_used", "updated_at"])
            bot_usage.payout_points += payout
            bot_usage.save(update_fields=["payout_points", "updated_at"])
            user_usage.payout_points += payout
            user_usage.save(update_fields=["payout_points", "updated_at"])
            inventory.shares_available += position_shares
            inventory.save(update_fields=["shares_available", "updated_at"])
            position.realized_points += payout - position.invested_points
            position.shares = 0
            position.invested_points = 0
            position.reserved_payout_points = 0
            position.status = MarketPosition.CLOSED
            position.average_cost = Decimal("0")
            position.save(update_fields=["shares", "invested_points", "reserved_payout_points", "realized_points", "status", "average_cost", "updated_at"])
            execution_price = _floor_money(Decimal(gross) / Decimal(position_shares)) if gross else Decimal("0")
            MarketOrder.objects.create(
                user=position.user,
                round=round_row,
                asset=position.asset,
                side=MarketOrder.SELL,
                quantity=position_shares,
                unit_price=execution_price,
                gross_points=gross,
                fee_points=fee,
                net_points=payout,
                source=MarketOrder.SETTLEMENT,
                idempotency_key=f"market_settlement_order:{round_row.pk}:{position.pk}",
            )
        if round_row.reserved_payout_points != 0:
            raise MarketError("market payout reserve did not fully release", HTTPStatus.CONFLICT)
        MarketAdminAudit.objects.create(round=round_row, action="settle_round", operator=operator, details={"positions": len(positions)})
        round_row.status = MarketRound.CLOSED
        round_row.updated_at = _now()
        round_row.save(update_fields=["status", "updated_at"])
        return round_row
