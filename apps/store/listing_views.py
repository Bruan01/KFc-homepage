# pyright: reportMissingImports=false
"""Creator shelf API views (kflowstore user listings)."""
from __future__ import annotations

from http import HTTPStatus

from django.views.decorators.http import require_GET, require_http_methods

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin, require_user
from apps.core.responses import json_error, json_ok

from .listing_services import (
    ListingError,
    admin_set_shelf,
    create_listing,
    listing_payload,
    redeem_listing,
    review_listing,
    set_listing_shelf,
    update_listing,
)
from .models import ListingRedemption, StoreListing


@require_user
def my_listings(request):
    if request.method == "POST":
        try:
            body = read_json(request)
            listing = create_listing(user=request.user, payload=body)
        except InvalidJSON:
            return json_error("invalid json")
        except ListingError as exc:
            return json_error(exc.message, status=exc.status)
        return json_ok({"item": listing_payload(listing)}, status=HTTPStatus.CREATED)
    if request.method != "GET":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET", "POST"])
    rows = StoreListing.objects.filter(seller_username=request.user.username).order_by("-updated_at", "-id")
    items = []
    for row in rows:
        items.append(listing_payload(row, stock_left=max(0, row.stock - row.redemptions.count())))
    return json_ok({"items": items})


@require_user
@require_http_methods(["PATCH", "PUT"])
def my_listing_update(request, listing_id: int):
    try:
        body = read_json(request)
        listing = update_listing(user=request.user, listing_id=listing_id, payload=body)
    except InvalidJSON:
        return json_error("invalid json")
    except ListingError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"item": listing_payload(listing)})


@require_user
@require_http_methods(["POST"])
def my_listing_shelf(request, listing_id: int):
    try:
        body = read_json(request)
        on_shelf = bool(body.get("onShelf"))
        listing = set_listing_shelf(user=request.user, listing_id=listing_id, on_shelf=on_shelf)
    except InvalidJSON:
        return json_error("invalid json")
    except ListingError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"item": listing_payload(listing)})


@require_GET
def listings(request):
    """Public active listings on the creator shelf."""
    rows = StoreListing.objects.filter(status=StoreListing.STATUS_ACTIVE).order_by("-updated_at", "-id")[:100]
    return json_ok({"items": [listing_payload(row, stock_left=max(0, row.stock - row.redemptions.count())) for row in rows]})


@require_user
@require_http_methods(["POST"])
def listing_redeem(request, listing_id: int):
    try:
        body = read_json(request)
        redemption, account, created = redeem_listing(
            user=request.user,
            listing_id=listing_id,
            idempotency_key=body.get("idempotencyKey"),
        )
    except InvalidJSON:
        return json_error("invalid json")
    except ListingError as exc:
        message = exc.message
        if message == "insufficient points":
            message = "积分不足：通过发帖、评论、被点赞赚取积分后再来购买"
        return json_error(message, status=exc.status)
    return json_ok({
        "ok": True,
        "created": created,
        "redemption": {
            "id": str(redemption.pk),
            "listingId": redemption.listing_id,
            "title": redemption.listing.title,
            "pointsPaid": int(redemption.points_paid),
            "payload": redemption.delivered_payload,
            "createdAt": redemption.created_at.isoformat(),
        },
        "balance": account["balance"],
    }, status=HTTPStatus.CREATED if created else HTTPStatus.OK)


@require_user
@require_GET
def my_purchases(request):
    rows = ListingRedemption.objects.filter(buyer=request.user).select_related("listing").order_by("-created_at")[:100]
    return json_ok({"items": [{
        "id": str(row.pk),
        "listingId": row.listing_id,
        "title": row.listing.title,
        "pointsPaid": int(row.points_paid),
        "payload": row.delivered_payload,
        "createdAt": row.created_at.isoformat(),
    } for row in rows]})


@require_user
@require_GET
def my_sales(request):
    rows = ListingRedemption.objects.filter(seller_username=request.user.username).select_related("listing").order_by("-created_at")[:100]
    return json_ok({"items": [{
        "id": str(row.pk),
        "title": row.listing.title,
        "buyer": row.buyer_username,
        "earning": int(row.seller_earning),
        "createdAt": row.created_at.isoformat(),
    } for row in rows]})


@require_admin(level=3)
@require_GET
def admin_pending(request):
    rows = StoreListing.objects.filter(status=StoreListing.STATUS_PENDING).order_by("created_at")[:200]
    return json_ok({"items": [listing_payload(row) for row in rows]})


@require_admin(level=3)
@require_http_methods(["POST"])
def admin_review(request, listing_id: int):
    try:
        body = read_json(request)
        approve = bool(body.get("approve"))
        reason = str(body.get("reason") or "")
        listing = review_listing(listing_id=listing_id, approve=approve, reviewer=request.kflow_admin["username"], reason=reason)
    except InvalidJSON:
        return json_error("invalid json")
    except ListingError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"item": listing_payload(listing)})


@require_admin(level=3)
@require_http_methods(["POST"])
def admin_shelf(request, listing_id: int):
    try:
        body = read_json(request)
        status = str(body.get("status") or "")
        listing = admin_set_shelf(listing_id=listing_id, status=status, reviewer=request.kflow_admin["username"], reason=str(body.get("reason") or ""))
    except InvalidJSON:
        return json_error("invalid json")
    except ListingError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"item": listing_payload(listing)})
