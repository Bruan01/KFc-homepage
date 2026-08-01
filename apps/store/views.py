from __future__ import annotations

from http import HTTPStatus

from django.views.decorators.http import require_GET

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin, require_user
from apps.core.responses import json_error, json_ok
from .models import StoreProduct, StoreRedemption
from .services import (
    StoreError,
    create_product,
    import_codes,
    product_payload,
    redeem_product,
    redemption_payload,
    update_product,
)


@require_GET
def products(request):
    rows = StoreProduct.objects.filter(status=StoreProduct.ACTIVE).order_by("-updated_at", "-id")
    return json_ok({"items": [product_payload(row) for row in rows]})


@require_user
@require_GET
def redemptions(request):
    rows = StoreRedemption.objects.filter(user=request.user).select_related("product", "code").order_by("-created_at")[:100]
    items = []
    for row in rows:
        try:
            items.append(redemption_payload(row, include_code=True))
        except ValueError:
            items.append(redemption_payload(row, include_code=False) | {"codeUnavailable": True})
    return json_ok({"items": items})


@require_user
def redeem(request):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    try:
        body = read_json(request)
        product_id = int(body.get("productId"))
    except (InvalidJSON, TypeError, ValueError):
        return json_error("productId and JSON body required")
    try:
        redemption, account, created = redeem_product(
            user=request.user,
            product_id=product_id,
            idempotency_key=body.get("idempotencyKey"),
        )
    except StoreError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({
        "ok": True,
        "created": created,
        "redemption": redemption_payload(redemption, include_code=True),
        "balance": account["balance"],
    }, status=HTTPStatus.CREATED if created else HTTPStatus.OK)


@require_admin(level=3, super_only=True)
def admin_products(request, product_id=None):
    if request.method == "GET":
        rows = StoreProduct.objects.all().order_by("-updated_at", "-id")
        return json_ok({"items": [product_payload(row) for row in rows]})
    try:
        body = read_json(request)
        if request.method == "POST" and product_id is None:
            row = create_product(payload=body, created_by=request.kflow_admin["username"])
        elif request.method in {"PUT", "PATCH"} and product_id is not None:
            row = update_product(product_id, body)
        else:
            from django.http import HttpResponseNotAllowed
            return HttpResponseNotAllowed(["GET", "POST", "PUT", "PATCH"])
    except InvalidJSON:
        return json_error("invalid json")
    except StoreError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"item": product_payload(row)}, status=HTTPStatus.CREATED if request.method == "POST" else HTTPStatus.OK)


@require_admin(level=3, super_only=True)
def admin_codes(request, product_id):
    if request.method == "GET":
        product = StoreProduct.objects.filter(pk=product_id).first()
        if not product:
            return json_error("store product not found", status=404)
        rows = product.codes.order_by("-created_at")[:500]
        return json_ok({"productId": product.pk, "items": [{
            "id": row.pk, "status": row.status, "digest": row.code_digest[:12],
            "importedBy": row.imported_by, "createdAt": row.created_at.isoformat(),
            "redeemedAt": row.redeemed_at.isoformat() if row.redeemed_at else None,
        } for row in rows]})
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        body = read_json(request)
        product = StoreProduct.objects.filter(pk=product_id).first()
        if not product:
            return json_error("store product not found", status=404)
        imported, skipped = import_codes(product=product, raw_codes=body.get("codes"), imported_by=request.kflow_admin["username"])
    except InvalidJSON:
        return json_error("invalid json")
    except StoreError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"ok": True, "imported": imported, "skipped": skipped}, status=HTTPStatus.CREATED)


@require_admin(level=3, super_only=True)
@require_GET
def admin_redemptions(request):
    rows = StoreRedemption.objects.select_related("user", "product", "code").order_by("-created_at")[:500]
    return json_ok({"items": [{
        **redemption_payload(row),
        "username": row.user.username,
        "codeDigest": row.code.code_digest[:12],
    } for row in rows]})
