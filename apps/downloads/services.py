from __future__ import annotations

import hashlib
import mimetypes
import os
import secrets
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils import timezone

from apps.catalog.models import Product, ProductPackage
from apps.core.permissions import get_admin_context
from apps.points.services import account_payload, active_entitlement, product_download_cost, now_iso
from .models import Download, DownloadRequest, UploadSession

ALLOWED_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}
CHUNK_UPLOAD_SIZE = 8 * 1024 * 1024
CHUNK_UPLOAD_TTL_SECONDS = 24 * 60 * 60


def safe_filename(name):
    clean = "".join(ch for ch in str(name) if ch.isalnum() or ch in {".", "-", "_"}).strip(".")
    return clean or f"package-{int(timezone.now().timestamp())}.zip"


def effective_limit_bytes(level):
    from apps.catalog.upload_limits import get_upload_limit_settings
    return get_upload_limit_settings()["limits"][f"lv{min(3, max(1, int(level)))}"]["bytes"]


def resolve_file(key, is_admin, pkg_id=None):
    product = Product.objects.filter(pk=int(key) if str(key).isdigit() else None).first() if str(key).isdigit() else Product.objects.filter(slug=key).first()
    if not product or (not is_admin and product.status != "published"):
        return None, None
    file_name, relative, size, sha = product.file_name, product.file_path, product.file_size, product.file_sha256
    if pkg_id:
        package = ProductPackage.objects.filter(pk=pkg_id, product=product).first()
        if package and package.file_path:
            file_name, relative, size, sha = package.file_name or file_name, package.file_path, package.file_size, package.file_sha256
    if not relative:
        return product, None
    target = (settings.BASE_DIR / relative).resolve()
    try:
        target.relative_to(settings.BASE_DIR.resolve())
    except ValueError:
        return product, None
    if not target.is_file():
        return product, None
    return product, {"path": target, "name": file_name or target.name, "size": size or target.stat().st_size, "sha256": sha or ""}


def parse_range(header, size):
    if not header:
        return None
    if not header.startswith("bytes=") or "," in header:
        return "invalid"
    raw = header[6:].strip()
    if "-" not in raw:
        return "invalid"
    start_raw, end_raw = raw.split("-", 1)
    try:
        if not start_raw:
            length = int(end_raw)
            if length <= 0:
                return "invalid"
            start, end = max(0, size - length), size - 1
        else:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
    except ValueError:
        return "invalid"
    if start < 0 or start >= size or end < start:
        return "invalid"
    return start, min(end, size - 1)


def stream_file(target, name, request):
    size = target.stat().st_size
    range_value = parse_range(request.headers.get("Range", ""), size)
    if range_value == "invalid":
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response
    start, end = (range_value if range_value else (0, size - 1))
    length = end - start + 1

    def iterator():
        with target.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block

    response = StreamingHttpResponse(iterator(), status=206 if range_value else 200, content_type=mimetypes.guess_type(str(target))[0] or "application/octet-stream")
    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = str(length)
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = f'attachment; filename="{name}"; filename*=UTF-8\'\'{quote(name)}'
    if range_value:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response


def account_download(request, product, user, file_info, pkg_id=None):
    if request.headers.get("Range", ""):
        return None
    admin = get_admin_context(request)
    now = now_iso()
    if admin:
        Download.objects.create(product=product, user=None, downloaded_at=now, ip=request.META.get("REMOTE_ADDR", ""), user_agent=request.META.get("HTTP_USER_AGENT", ""))
        return None
    existing = Download.objects.filter(product=product, user=user).order_by("-id").first()
    approved = DownloadRequest.objects.filter(product=product, user=user, status="approved", consumed_at__isnull=True).order_by("-id").first()
    entitlement = active_entitlement(user, product) if existing and not approved else None
    if existing and not approved and not entitlement:
        cost = product_download_cost(product)
        account = account_payload(user)
        from apps.core.responses import json_error
        return json_error("download quota used", status=403, canRedeemPoints=cost is not None, pointCost=cost, pointsBalance=account["balance"], productId=product.pk, productName=product.name)
    Download.objects.create(product=product, user=user, request=approved, entitlement=entitlement, downloaded_at=now, ip=request.META.get("REMOTE_ADDR", ""), user_agent=request.META.get("HTTP_USER_AGENT", ""))
    if approved:
        approved.consumed_at = now
        approved.save(update_fields=["consumed_at"])
    elif entitlement:
        entitlement.remaining_count = max(0, entitlement.remaining_count - 1)
        if entitlement.remaining_count == 0:
            entitlement.consumed_at = now
        entitlement.save(update_fields=["remaining_count", "consumed_at"])
    return None
