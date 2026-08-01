from __future__ import annotations

from http import HTTPStatus

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.points.services import PointsError, account_payload, apply_ledger
from .crypto import decrypt_code, digest_code, encrypt_code
from .models import StoreCode, StoreProduct, StoreRedemption


class StoreError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = int(status)


def product_payload(product: StoreProduct, *, include_stock: bool = True) -> dict:
    available = product.codes.filter(status=StoreCode.AVAILABLE).count() if include_stock else None
    return {
        "id": product.pk,
        "slug": product.slug,
        "name": product.name,
        "summary": product.summary,
        "description": product.description,
        "coverUrl": product.cover_url,
        "pointsCost": int(product.points_cost),
        "perUserLimit": int(product.per_user_limit),
        "status": product.status,
        "stock": available,
        "createdBy": product.created_by,
        "createdAt": product.created_at.isoformat(),
        "updatedAt": product.updated_at.isoformat(),
    }


def redemption_payload(row: StoreRedemption, *, include_code: bool = False) -> dict:
    result = {
        "id": str(row.pk),
        "productId": row.product_id,
        "productName": row.product.name,
        "productSlug": row.product.slug,
        "pointsCost": int(row.points_cost),
        "status": row.status,
        "createdAt": row.created_at.isoformat(),
        "revokedAt": row.revoked_at.isoformat() if row.revoked_at else None,
    }
    if include_code:
        result["code"] = decrypt_code(row.code.code_ciphertext)
    return result


def _validate_idempotency(value) -> str:
    key = str(value or "").strip()
    if len(key) < 8 or len(key) > 160:
        raise StoreError("valid idempotency key required")
    return key


def redeem_product(*, user, product_id: int, idempotency_key: str):
    key = _validate_idempotency(idempotency_key)
    with transaction.atomic():
        existing = StoreRedemption.objects.select_related("product", "code", "point_ledger").filter(idempotency_key=key).first()
        if existing:
            if existing.user_id != user.pk:
                raise StoreError("idempotency key conflict", HTTPStatus.CONFLICT)
            return existing, account_payload(user), False

        product = StoreProduct.objects.select_for_update().filter(pk=product_id, status=StoreProduct.ACTIVE).first()
        if not product:
            raise StoreError("store product not found or inactive", HTTPStatus.NOT_FOUND)
        redeemed_count = StoreRedemption.objects.filter(user=user, product=product, status=StoreRedemption.FULFILLED).count()
        if redeemed_count >= product.per_user_limit:
            raise StoreError("per-user redemption limit reached", HTTPStatus.CONFLICT)
        code = StoreCode.objects.select_for_update().filter(product=product, status=StoreCode.AVAILABLE).order_by("id").first()
        if not code:
            raise StoreError("store product is sold out", HTTPStatus.CONFLICT)

        try:
            ledger, _ = apply_ledger(
                user=user,
                event_type="store_redeem",
                points_delta=-int(product.points_cost),
                idempotency_key=f"store_redeem:{key}",
                description=f"K 士多兑换：{product.name}",
                reference_type="store_redemption",
                reference_id=key,
            )
        except PointsError as exc:
            raise StoreError(exc.message, exc.status) from exc
        redemption = StoreRedemption.objects.create(
            user=user,
            product=product,
            code=code,
            point_ledger=ledger,
            points_cost=product.points_cost,
            idempotency_key=key,
        )
        code.status = StoreCode.REDEEMED
        code.redeemed_at = timezone.now()
        code.save(update_fields=["status", "redeemed_at"])
        return redemption, account_payload(user), True


def create_product(*, payload: dict, created_by: str) -> StoreProduct:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise StoreError("name required")
    slug = slugify(str(payload.get("slug") or name).strip())
    if not slug:
        raise StoreError("valid slug required")
    try:
        points_cost = int(payload.get("pointsCost", 0))
        per_user_limit = int(payload.get("perUserLimit", 1))
    except (TypeError, ValueError) as exc:
        raise StoreError("pointsCost and perUserLimit must be integers") from exc
    if points_cost < 0 or per_user_limit < 1:
        raise StoreError("invalid product price or per-user limit")
    status = str(payload.get("status") or StoreProduct.DRAFT)
    if status not in {StoreProduct.DRAFT, StoreProduct.ACTIVE, StoreProduct.ARCHIVED}:
        raise StoreError("invalid product status")
    try:
        return StoreProduct.objects.create(
            slug=slug,
            name=name,
            summary=str(payload.get("summary") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            cover_url=str(payload.get("coverUrl") or "").strip(),
            points_cost=points_cost,
            per_user_limit=per_user_limit,
            status=status,
            created_by=created_by,
        )
    except IntegrityError as exc:
        raise StoreError("store product slug already exists", HTTPStatus.CONFLICT) from exc


def update_product(product_id: int, payload: dict) -> StoreProduct:
    product = StoreProduct.objects.filter(pk=product_id).first()
    if not product:
        raise StoreError("store product not found", HTTPStatus.NOT_FOUND)
    for field, key in {
        "name": "name", "summary": "summary", "description": "description", "cover_url": "coverUrl",
        "status": "status",
    }.items():
        if key in payload:
            setattr(product, field, str(payload[key] or "").strip())
    if "pointsCost" in payload:
        try:
            product.points_cost = int(payload["pointsCost"])
        except (TypeError, ValueError) as exc:
            raise StoreError("pointsCost must be an integer") from exc
    if "perUserLimit" in payload:
        try:
            product.per_user_limit = int(payload["perUserLimit"])
        except (TypeError, ValueError) as exc:
            raise StoreError("perUserLimit must be an integer") from exc
    if product.points_cost < 0 or product.per_user_limit < 1:
        raise StoreError("invalid product price or per-user limit")
    if product.status not in {StoreProduct.DRAFT, StoreProduct.ACTIVE, StoreProduct.ARCHIVED}:
        raise StoreError("invalid product status")
    product.save()
    return product


def import_codes(*, product: StoreProduct, raw_codes, imported_by: str) -> tuple[int, int]:
    if isinstance(raw_codes, str):
        candidates = raw_codes.splitlines()
    elif isinstance(raw_codes, list):
        candidates = raw_codes
    else:
        raise StoreError("codes must be a newline-separated string or list")
    normalized = []
    seen = set()
    for raw in candidates:
        code = str(raw or "").strip()
        if not code or code in seen:
            continue
        if len(code) > 1000:
            raise StoreError("兑换码长度不能超过 1000 个字符")
        seen.add(code)
        normalized.append(code)
    if len(normalized) > 5000:
        raise StoreError("一次最多导入 5000 个兑换码")
    imported = 0
    skipped = 0
    with transaction.atomic():
        locked_product = StoreProduct.objects.select_for_update().get(pk=product.pk)
        existing = set(locked_product.codes.values_list("code_digest", flat=True))
        rows = []
        for code in normalized:
            digest = digest_code(code)
            if digest in existing:
                skipped += 1
                continue
            rows.append(StoreCode(product=locked_product, code_ciphertext=encrypt_code(code), code_digest=digest, imported_by=imported_by))
            existing.add(digest)
        StoreCode.objects.bulk_create(rows)
        imported = len(rows)
    return imported, skipped
