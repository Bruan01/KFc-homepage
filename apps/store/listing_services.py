# pyright: reportMissingImports=false
"""Creator shelf (kflowstore user listings): create, review, trade."""
from __future__ import annotations

from http import HTTPStatus

from django.db import transaction
from django.utils import timezone

from apps.points.services import PointsError, account_payload, apply_ledger
from .models import ListingRedemption, StoreListing

MAX_ACTIVE_LISTINGS_PER_SELLER = 10
MIN_PRICE_POINTS = 10


class ListingError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = int(status)


def listing_payload(listing: StoreListing, *, include_deliverable: bool = False, stock_left: int | None = None) -> dict:
    result = {
        "id": listing.pk,
        "seller": listing.seller_username,
        "title": listing.title,
        "summary": listing.summary,
        "description": listing.description,
        "coverUrl": listing.cover_url,
        "pricePoints": int(listing.price_points),
        "stock": listing.stock,
        "stockLeft": stock_left,
        "perUserLimit": int(listing.per_user_limit),
        "deliverableType": listing.deliverable_type,
        "status": listing.status,
        "reviewReason": listing.review_reason,
        "soldCount": int(listing.sold_count),
        "createdAt": listing.created_at.isoformat(),
        "updatedAt": listing.updated_at.isoformat(),
    }
    if include_deliverable:
        result["deliverableText"] = listing.deliverable_text
        result["deliverableLink"] = listing.deliverable_link
    return result


def _parse_listing_input(payload: dict, *, for_update: bool = False) -> dict:
    title = str(payload.get("title") or "").strip()
    if not title or len(title) > 160:
        raise ListingError("标题必填且不超过 160 字")
    price = payload.get("pricePoints", None)
    stock = payload.get("stock", None)
    per_user_limit = payload.get("perUserLimit", 1)
    deliverable_type = str(payload.get("deliverableType") or StoreListing.DELIVERABLE_TEXT).strip()
    if deliverable_type not in {StoreListing.DELIVERABLE_TEXT, StoreListing.DELIVERABLE_CODE, StoreListing.DELIVERABLE_LINK}:
        raise ListingError("交付方式必须是 text / code / link")
    try:
        price = int(price) if price is not None else None
        stock = int(stock) if stock is not None else None
        per_user_limit = int(per_user_limit)
    except (TypeError, ValueError) as exc:
        raise ListingError("价格与库存必须是整数") from exc
    if price is not None and price < MIN_PRICE_POINTS:
        raise ListingError(f"定价不能低于 {MIN_PRICE_POINTS} 积分")
    if per_user_limit < 1:
        raise ListingError("每人限购至少 1 件")
    if deliverable_type == StoreListing.DELIVERABLE_CODE and stock == 0:
        raise ListingError("兑换码商品必须填写库存数量")
    link = str(payload.get("deliverableLink") or "").strip()
    if deliverable_type == StoreListing.DELIVERABLE_LINK:
        if not link.startswith(("http://", "https://")):
            raise ListingError("外部链接必须是 http/https 地址")
    if len(link) > 500:
        raise ListingError("外部链接过长")
    text = str(payload.get("deliverableText") or "").strip()
    codes = str(payload.get("deliverableCodes") or "").strip()
    if deliverable_type == StoreListing.DELIVERABLE_CODE and not codes and not for_update:
        raise ListingError("兑换码商品必须填写兑换码内容")
    if deliverable_type == StoreListing.DELIVERABLE_TEXT and not text and not for_update:
        raise ListingError("文本交付商品必须填写交付内容")
    cover = str(payload.get("coverUrl") or "").strip()
    if cover and not cover.startswith(("http://", "https://", "/")):
        raise ListingError("封面必须是 http/https 地址或本站路径")
    return {
        "title": title,
        "summary": str(payload.get("summary") or "").strip()[:300],
        "description": str(payload.get("description") or "").strip(),
        "cover_url": cover,
        "price_points": price,
        "stock": stock,
        "per_user_limit": per_user_limit,
        "deliverable_type": deliverable_type,
        "deliverable_text": text[:5000],
        "deliverable_codes": codes[:100000],
        "deliverable_link": link,
    }


def create_listing(*, user, payload: dict) -> StoreListing:
    from apps.points.models import PointAccount

    account = PointAccount.objects.filter(user=user).first()
    if not account or int(account.reputation_level or 0) < 1:
        raise ListingError("需要正式成员（LV1）及以上才能上架商品，先去社区发帖互动升级吧", HTTPStatus.FORBIDDEN)
    data = _parse_listing_input(payload)
    active_count = StoreListing.objects.filter(
        seller_username=user.username,
        status__in=[StoreListing.STATUS_DRAFT, StoreListing.STATUS_PENDING, StoreListing.STATUS_ACTIVE],
    ).count()
    if active_count >= MAX_ACTIVE_LISTINGS_PER_SELLER:
        raise ListingError(f"每个用户最多同时持有 {MAX_ACTIVE_LISTINGS_PER_SELLER} 个商品（含审核中）", HTTPStatus.CONFLICT)
    listing = StoreListing.objects.create(
        seller_username=user.username,
        title=data["title"],
        summary=data["summary"],
        description=data["description"],
        cover_url=data["cover_url"],
        price_points=data["price_points"] or MIN_PRICE_POINTS,
        stock=data["stock"] if data["stock"] is not None else 0,
        per_user_limit=data["per_user_limit"],
        deliverable_type=data["deliverable_type"],
        deliverable_text=data["deliverable_text"],
        deliverable_codes=data["deliverable_codes"],
        deliverable_link=data["deliverable_link"],
        status=StoreListing.STATUS_PENDING,  # all new listings go to review
    )
    return listing


def update_listing(*, user, listing_id: int, payload: dict) -> StoreListing:
    listing = StoreListing.objects.filter(pk=listing_id, seller_username=user.username).first()
    if not listing:
        raise ListingError("商品不存在或无权操作", HTTPStatus.NOT_FOUND)
    if listing.status in {StoreListing.STATUS_PENDING}:
        raise ListingError("审核中的商品暂不能修改")
    data = _parse_listing_input(payload, for_update=True)
    for field in ("title", "summary", "description", "cover_url", "deliverable_text", "deliverable_codes", "deliverable_link"):
        if data[field]:
            setattr(listing, field, data[field])
    if data["price_points"] is not None:
        listing.price_points = data["price_points"]
    if data["stock"] is not None:
        listing.stock = data["stock"]
    listing.per_user_limit = data["per_user_limit"]
    if listing.status == StoreListing.STATUS_REJECTED:
        listing.status = StoreListing.STATUS_PENDING  # re-submit to review
        listing.review_reason = ""
    listing.save()
    return listing


def set_listing_shelf(*, user, listing_id: int, on_shelf: bool) -> StoreListing:
    listing = StoreListing.objects.filter(pk=listing_id, seller_username=user.username).first()
    if not listing:
        raise ListingError("商品不存在或无权操作", HTTPStatus.NOT_FOUND)
    if on_shelf and listing.status != StoreListing.STATUS_ACTIVE:
        raise ListingError("仅审核通过的商品可上架")
    if not on_shelf and listing.status not in {StoreListing.STATUS_ACTIVE}:
        raise ListingError("当前状态无法下架")
    listing.status = StoreListing.STATUS_ACTIVE if on_shelf else StoreListing.STATUS_OFF_SHELF
    listing.save(update_fields=["status", "updated_at"])
    return listing


def review_listing(*, listing_id: int, approve: bool, reviewer: str, reason: str = "") -> StoreListing:
    listing = StoreListing.objects.filter(pk=listing_id, status=StoreListing.STATUS_PENDING).first()
    if not listing:
        raise ListingError("没有待审核的该商品", HTTPStatus.NOT_FOUND)
    listing.status = StoreListing.STATUS_ACTIVE if approve else StoreListing.STATUS_REJECTED
    listing.review_reason = str(reason or "").strip()[:1000]
    listing.reviewed_by = reviewer
    listing.reviewed_at = timezone.now()
    listing.save(update_fields=["status", "review_reason", "reviewed_by", "reviewed_at", "updated_at"])
    return listing


def admin_set_shelf(*, listing_id: int, status: str, reviewer: str, reason: str = "") -> StoreListing:
    listing = StoreListing.objects.filter(pk=listing_id).first()
    if not listing:
        raise ListingError("商品不存在", HTTPStatus.NOT_FOUND)
    if status not in {StoreListing.STATUS_ACTIVE, StoreListing.STATUS_OFF_SHELF}:
        raise ListingError("非法状态")
    listing.status = status
    listing.review_reason = str(reason or "").strip()[:1000]
    listing.reviewed_by = reviewer
    listing.save(update_fields=["status", "review_reason", "reviewed_by", "updated_at"])
    return listing


def _next_deliverable(listing: StoreListing) -> str | None:
    """Pop the next deliverable for the listing; None when sold out."""
    if listing.deliverable_type == StoreListing.DELIVERABLE_TEXT:
        return listing.deliverable_text
    if listing.deliverable_type == StoreListing.DELIVERABLE_LINK:
        return listing.deliverable_link
    # code type: pull first available line, tracked by stock counter
    lines = [line.strip() for line in listing.deliverable_codes.splitlines() if line.strip()]
    consumed = ListingRedemption.objects.filter(listing=listing).count()
    if consumed >= len(lines) or (listing.stock and consumed >= listing.stock):
        return None
    return lines[consumed]


def redeem_listing(*, user, listing_id: int, idempotency_key: str):
    key = str(idempotency_key or "").strip()
    if len(key) < 8 or len(key) > 160:
        raise ListingError("valid idempotency key required")
    with transaction.atomic():
        existing = ListingRedemption.objects.filter(idempotency_key=key).first()
        if existing:
            if existing.buyer_id != user.pk:
                raise ListingError("idempotency key conflict", HTTPStatus.CONFLICT)
            return existing, account_payload(user), False

        listing = StoreListing.objects.select_for_update().filter(
            pk=listing_id, status=StoreListing.STATUS_ACTIVE
        ).first()
        if not listing:
            raise ListingError("商品不存在或未在售", HTTPStatus.NOT_FOUND)
        existing = ListingRedemption.objects.filter(idempotency_key=key).first()
        if existing:
            if existing.buyer_id != user.pk:
                raise ListingError("idempotency key conflict", HTTPStatus.CONFLICT)
            return existing, account_payload(user), False
        if listing.seller_username == user.username:
            raise ListingError("不能购买自己的商品", HTTPStatus.FORBIDDEN)
        bought = ListingRedemption.objects.filter(listing=listing, buyer=user).count()
        if bought >= listing.per_user_limit:
            raise ListingError("已达到每人限购数量", HTTPStatus.CONFLICT)
        payload = _next_deliverable(listing)
        if payload is None:
            raise ListingError("商品已售罄", HTTPStatus.CONFLICT)

        try:
            buyer_ledger, _ = apply_ledger(
                user=user,
                event_type="listing_redeem",
                points_delta=-int(listing.price_points),
                idempotency_key=f"listing_redeem:{key}",
                description=f"kflowstore 购买：{listing.title}",
                reference_type="store_listing",
                reference_id=listing.pk,
            )
            seller = None
            from apps.accounts.models import User

            try:
                seller = User.objects.get(username=listing.seller_username)
            except User.DoesNotExist:
                pass
            seller_earning = int(listing.price_points)  # M3: no platform fee
            seller_ledger_id = 0
            if seller is not None:
                seller_ledger, _ = apply_ledger(
                    user=seller,
                    event_type="listing_sold",
                    points_delta=seller_earning,
                    idempotency_key=f"listing_sold:{key}",
                    description=f"kflowstore 售出：{listing.title}",
                    reference_type="store_listing",
                    reference_id=listing.pk,
                )
                seller_ledger_id = seller_ledger.pk
        except PointsError as exc:
            raise ListingError(exc.message, exc.status) from exc

        redemption = ListingRedemption.objects.create(
            listing=listing,
            buyer=user,
            buyer_username=user.username,
            seller_username=listing.seller_username,
            points_paid=int(listing.price_points),
            seller_earning=seller_earning,
            delivered_payload=payload,
            buyer_ledger_id=buyer_ledger.pk,
            seller_ledger_id=seller_ledger_id,
            idempotency_key=key,
        )
        listing.sold_count = listing.sold_count + 1
        if listing.stock:
            listing.stock = max(0, listing.stock - 1)
            if listing.stock == 0:
                listing.status = StoreListing.STATUS_OFF_SHELF
        listing.save(update_fields=["sold_count", "stock", "status", "updated_at"])

    # 售出后给买卖双方即时检查勋章（事务外，失败不影响交易）
    try:
        from apps.gamification.services import check_user_achievements
        from apps.notifications.services import notify as notify_user

        try:
            from apps.accounts.models import User as _User

            seller_user = _User.objects.filter(username=listing.seller_username).first()
            if seller_user:
                notify_user(
                    recipient=seller_user, type_="sale",
                    title=f"商品「{listing.title[:40]}」已售出",
                    body=f"买家 {user.username} 支付 {int(listing.price_points)} 积分，收入已到账",
                    link="/store",
                )
        except Exception:
            pass
        check_user_achievements(user)
        try:
            from apps.accounts.models import User as _User

            seller_user = _User.objects.filter(username=listing.seller_username).first()
            if seller_user:
                check_user_achievements(seller_user)
        except Exception:
            pass
    except Exception:
        pass
    return redemption, account_payload(user), True
