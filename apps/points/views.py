import secrets
from http import HTTPStatus

from django.db import transaction
from django.db.models import Q
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User
from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin, require_user
from apps.core.responses import json_error, json_ok
from apps.downloads.models import DownloadEntitlement
from .models import PointAccount, PointLedger
from .services import (
    PointsError, account_payload, apply_ledger, award_daily_activity, ensure_account,
    get_rules, ledger_payload, now_iso, redeem_download, save_rules,
)


@require_user
@require_GET
def me(request):
    with transaction.atomic():
        daily, awarded = award_daily_activity(request.user)
        payload = account_payload(request.user)
    payload["dailyAwarded"] = bool(awarded)
    payload["dailyDelta"] = int(daily.delta) if daily is not None and awarded else 0
    return json_ok(payload)


@require_GET
def rules(request):
    return json_ok({"item": get_rules()})


@require_user
@require_GET
def ledger(request):
    try:
        page = max(1, int(request.GET.get("page", "1")))
        page_size = max(1, min(100, int(request.GET.get("pageSize", "30"))))
    except ValueError:
        page, page_size = 1, 30
    queryset = PointLedger.objects.filter(user=request.user).order_by("-id")
    total = queryset.count()
    rows = queryset[(page - 1) * page_size: page * page_size]
    return json_ok({"items": [ledger_payload(row) for row in rows], "total": total, "page": page, "pageSize": page_size})


@require_user
@require_GET
def entitlements(request):
    rows = DownloadEntitlement.objects.filter(user=request.user).select_related("product").order_by("-id")[:100]
    return json_ok({"items": [{
        "id": row.pk, "productId": row.product_id, "productName": row.product.name,
        "productSlug": row.product.slug, "source": row.source, "cost": int(row.cost or 0),
        "remainingCount": int(row.remaining_count or 0), "createdAt": row.created_at,
        "expiresAt": row.expires_at, "consumedAt": row.consumed_at,
    } for row in rows]})


@require_user
@require_POST
def redeem(request):
    try:
        body = read_json(request)
        product_id = int(body.get("productId"))
    except (InvalidJSON, TypeError, ValueError):
        return json_error("productId and JSON body required")
    try:
        with transaction.atomic():
            entitlement, account, created = redeem_download(
                user=request.user, product_id=product_id,
                idempotency_key=str(body.get("idempotencyKey") or "").strip(),
            )
    except PointsError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({
        "ok": True, "created": created, "entitlementId": entitlement.pk,
        "productId": entitlement.product_id, "cost": int(entitlement.cost or 0),
        "expiresAt": entitlement.expires_at, "balance": account["balance"],
    }, status=HTTPStatus.CREATED if created else HTTPStatus.OK)


@require_admin(level=3)
def admin_settings(request):
    if request.method == "GET":
        return json_ok({"item": get_rules()})
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("invalid json")
    try:
        with transaction.atomic():
            result = save_rules(body, request.kflow_admin["username"])
    except PointsError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"ok": True, "item": result})


@require_admin()
@require_GET
def admin_accounts(request):
    search = request.GET.get("search", "").strip()
    users = User.objects.select_related("point_account")
    if search:
        users = users.filter(Q(username__icontains=search) | Q(email__icontains=search))
    users = users.order_by("-point_account__contribution_score", "-id")[:200]
    items = []
    for user in users:
        try:
            account = user.point_account
        except PointAccount.DoesNotExist:
            account = None
        items.append({
            "user_id": user.pk, "username": user.username, "email": user.email,
            "balance": account.balance if account else None,
            "total_earned": account.total_earned if account else None,
            "total_spent": account.total_spent if account else None,
            "contribution_score": account.contribution_score if account else None,
            "reputation_level": account.reputation_level if account else None,
            "status": account.status if account else None,
            "last_active_date": account.last_active_date if account else None,
        })
    return json_ok({"items": items})


@require_admin(level=3)
@require_POST
def adjust(request):
    try:
        body = read_json(request)
        user_id = int(body.get("userId"))
        points_delta = int(body.get("pointsDelta", 0))
        contribution_delta = int(body.get("contributionDelta", 0))
    except (InvalidJSON, TypeError, ValueError):
        return json_error("valid adjustment body required")
    reason = str(body.get("reason") or "").strip()
    if not reason or (points_delta == 0 and contribution_delta == 0):
        return json_error("reason and non-zero adjustment required")
    user = User.objects.filter(pk=user_id).first()
    if not user:
        return json_error("user not found", status=404)
    try:
        with transaction.atomic():
            row, _ = apply_ledger(
                user=user, event_type="admin_adjustment", points_delta=points_delta,
                contribution_delta=contribution_delta,
                idempotency_key=f"admin_adjustment:{request.kflow_admin['username']}:{secrets.token_hex(16)}",
                description=reason, reference_type="admin",
                reference_id=request.kflow_admin["username"], created_by=request.kflow_admin["username"],
            )
            account = account_payload(user)
    except PointsError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"ok": True, "ledger": ledger_payload(row), "account": account})


def _set_status(request, status):
    try:
        body = read_json(request)
        user_id = int(body.get("userId"))
    except (InvalidJSON, TypeError, ValueError):
        return json_error("userId required")
    user = User.objects.filter(pk=user_id).first()
    if not user:
        return json_error("user not found", status=404)
    with transaction.atomic():
        account = ensure_account(user)
        account.status = status
        account.updated_at = now_iso()
        account.save(update_fields=["status", "updated_at"])
    return json_ok({"ok": True, "userId": user_id, "status": status})


@require_admin(level=3)
@require_POST
def freeze(request):
    return _set_status(request, "frozen")


@require_admin(level=3)
@require_POST
def unfreeze(request):
    return _set_status(request, "active")
