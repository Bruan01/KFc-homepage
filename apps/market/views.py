from __future__ import annotations

from http import HTTPStatus

from django.http import HttpResponseNotAllowed
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin, require_user
from apps.core.responses import json_error, json_ok
from apps.points.services import account_payload
from .models import MarketAdminAudit, MarketAsset, MarketBotInventory, MarketOrder, MarketRound, MarketTreasuryLedger
from .services import (
    MarketError,
    _order_payload,
    configure_inventory,
    control_round,
    create_asset,
    create_round,
    current_round,
    fund_round,
    get_quote,
    place_order,
    portfolio_payload,
    quote_payload,
    round_payload,
    update_asset,
)


@require_GET
def round_info(request):
    row = current_round()
    if not row:
        return json_ok({"item": None, "message": "当前没有开放的 K 股市轮次。"})
    return json_ok({"item": round_payload(row)})


@require_GET
def quotes(request):
    row = current_round()
    if not row:
        return json_ok({"round": None, "items": []})
    assets = MarketAsset.objects.filter(active=True, bot_inventory__round=row).distinct().order_by("code")
    inventory_by_asset = {
        inventory.asset_id: inventory.shares_available
        for inventory in MarketBotInventory.objects.filter(round=row, asset__in=assets)
    }
    items = [quote_payload(get_quote(row, asset)) | {"inventory": inventory_by_asset.get(asset.pk, 0)} for asset in assets]
    return json_ok({"round": round_payload(row), "items": items})


@require_user
@require_GET
def portfolio(request):
    row = current_round()
    return json_ok({"round": round_payload(row), "balance": account_payload(request.user)["balance"], "items": portfolio_payload(request.user, row) if row else []})


@require_user
def orders(request):
    if request.method == "POST":
        return order(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET", "POST"])
    rows = MarketOrder.objects.filter(user=request.user).select_related("asset").order_by("-created_at")[:100]
    return json_ok({"items": [{
        "id": str(row.pk), "roundId": row.round_id, "assetId": row.asset_id, "assetCode": row.asset.code,
        "side": row.side, "quantity": row.quantity, "unitPrice": str(row.unit_price),
        "grossPoints": row.gross_points, "feePoints": row.fee_points, "netPoints": row.net_points,
        "status": row.status, "source": row.source,
        "createdAt": row.created_at.isoformat(),
    } for row in rows]})


@require_user
def order(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = read_json(request)
        asset_id = int(body.get("assetId"))
        quantity = int(body.get("quantity"))
    except (InvalidJSON, TypeError, ValueError):
        return json_error("assetId, quantity and JSON body required")
    try:
        row, account, created = place_order(
            user=request.user,
            asset_id=asset_id,
            side=str(body.get("side") or "").strip().lower(),
            quantity=quantity,
            idempotency_key=body.get("idempotencyKey"),
        )
    except MarketError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"ok": True, "created": created, "order": _order_payload(row), "balance": account["balance"]}, status=HTTPStatus.CREATED if created else HTTPStatus.OK)


@require_admin(level=3, super_only=True)
def admin_rounds(request):
    if request.method == "GET":
        rows = MarketRound.objects.all().order_by("-starts_at", "-id")[:100]
        return json_ok({"items": [round_payload(row) for row in rows]})
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        row = create_round(payload=read_json(request), created_by=request.kflow_admin["username"])
    except InvalidJSON:
        return json_error("invalid json")
    except MarketError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"item": round_payload(row)}, status=HTTPStatus.CREATED)


@require_admin(level=3, super_only=True)
def admin_assets(request):
    if request.method == "GET":
        rows = MarketAsset.objects.all().order_by("code")
        return json_ok({"items": [{"id": row.pk, "code": row.code, "name": row.name, "description": row.description, "basePrice": str(row.base_price), "active": row.active} for row in rows]})
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        row = create_asset(payload=read_json(request), operator=request.kflow_admin["username"])
    except InvalidJSON:
        return json_error("invalid json")
    except MarketError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"item": {"id": row.pk, "code": row.code, "name": row.name, "basePrice": str(row.base_price), "active": row.active}}, status=HTTPStatus.CREATED)


@require_admin(level=3, super_only=True)
def admin_asset_detail(request, asset_id):
    if request.method != "PATCH":
        return HttpResponseNotAllowed(["PATCH"])
    try:
        row = update_asset(asset_id=asset_id, payload=read_json(request), operator=request.kflow_admin["username"])
    except InvalidJSON:
        return json_error("invalid json")
    except MarketError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"item": {"id": row.pk, "code": row.code, "name": row.name, "description": row.description, "basePrice": str(row.base_price), "active": row.active}})


@require_admin(level=3, super_only=True)
def admin_inventory(request):
    if request.method == "GET":
        round_id = request.GET.get("roundId")
        rows = MarketBotInventory.objects.select_related("asset", "round").order_by("round_id", "asset__code")
        if round_id:
            rows = rows.filter(round_id=round_id)
        return json_ok({"items": [{"roundId": row.round_id, "assetId": row.asset_id, "assetCode": row.asset.code, "initialShares": row.initial_shares, "sharesAvailable": row.shares_available} for row in rows[:500]]})
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        body = read_json(request)
        inventory = configure_inventory(round_id=body.get("roundId"), asset_id=body.get("assetId"), shares=body.get("shares"), operator=request.kflow_admin["username"])
    except InvalidJSON:
        return json_error("invalid inventory payload")
    except MarketError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"ok": True, "roundId": inventory.round_id, "assetId": inventory.asset_id, "shares": inventory.initial_shares})


@require_admin(level=3, super_only=True)
def admin_fund(request, round_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = read_json(request)
        round_row, _ = fund_round(round_id=round_id, amount=body.get("amount"), operator=request.kflow_admin["username"], idempotency_key=body.get("idempotencyKey"))
    except InvalidJSON:
        return json_error("positive amount required")
    except MarketError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"ok": True, "round": round_payload(round_row)})


@require_admin(level=3, super_only=True)
def admin_control(request, round_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        action = str(read_json(request).get("action") or "").strip().lower()
    except InvalidJSON:
        return json_error("invalid json")
    try:
        row = control_round(round_id=round_id, action=action, operator=request.kflow_admin["username"])
    except MarketError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"ok": True, "item": round_payload(row)})


@require_admin(level=3, super_only=True)
@require_GET
def admin_orders(request):
    rows = MarketOrder.objects.select_related("user", "asset").order_by("-created_at")[:500]
    return json_ok({"items": [{"id": str(row.pk), "roundId": row.round_id, "username": row.user.username, "assetCode": row.asset.code, "side": row.side, "source": row.source, "status": row.status, "quantity": row.quantity, "unitPrice": str(row.unit_price), "grossPoints": row.gross_points, "feePoints": row.fee_points, "netPoints": row.net_points, "createdAt": row.created_at.isoformat()} for row in rows]})


@require_admin(level=3, super_only=True)
@require_GET
def admin_treasury(request):
    rows = MarketTreasuryLedger.objects.select_related("round").order_by("-created_at")[:500]
    return json_ok({"items": [{"id": row.pk, "roundId": row.round_id, "eventType": row.event_type, "delta": row.delta, "balanceAfter": row.balance_after, "feePoints": row.fee_points, "referenceId": row.reference_id, "idempotencyKey": row.idempotency_key, "createdBy": row.created_by, "createdAt": row.created_at.isoformat()} for row in rows]})


@require_admin(level=3, super_only=True)
@require_GET
def admin_audits(request):
    rows = MarketAdminAudit.objects.select_related("round").order_by("-created_at")[:500]
    return json_ok({"items": [{"id": row.pk, "roundId": row.round_id, "action": row.action, "operator": row.operator, "details": row.details, "createdAt": row.created_at.isoformat()} for row in rows]})
