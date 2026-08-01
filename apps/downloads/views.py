from __future__ import annotations

import hashlib
import json
import shutil
import secrets
import time
from http import HTTPStatus
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.catalog.models import Product, ProductPackage
from apps.catalog.upload_limits import get_upload_limit_settings
from apps.core.http import InvalidJSON, client_ip, read_json
from apps.core.permissions import get_admin_context, require_admin, require_user
from apps.core.responses import json_error, json_ok
from apps.points.services import account_payload, active_entitlement, product_download_cost, now_iso
from .models import Download, DownloadEntitlement, DownloadRequest, UploadSession
from .services import ALLOWED_EXTENSIONS, CHUNK_UPLOAD_SIZE, CHUNK_UPLOAD_TTL_SECONDS, effective_limit_bytes, resolve_file, safe_filename, stream_file


def _user_request_items(queryset):
    return [{
        "id": row.pk, "product_id": row.product_id, "product_name": row.product.name if row.product_id else "",
        "product_slug": row.product.slug if row.product_id else "", "reason": row.reason,
        "status": row.status, "created_at": row.created_at, "reviewed_at": row.reviewed_at,
        "review_note": row.review_note, "consumed_at": row.consumed_at,
    } for row in queryset.select_related("product")]


@require_user
@require_GET
def history(request):
    rows = Download.objects.filter(user=request.user).select_related("product").order_by("-downloaded_at")[:200]
    return json_ok({"items": [{
        "id": row.pk, "product_id": row.product_id, "product_name": row.product.name if row.product_id else "",
        "product_slug": row.product.slug if row.product_id else "", "product_version": row.product.version if row.product_id else "",
        "product_file": row.product.file_name if row.product_id else "", "downloaded_at": row.downloaded_at,
    } for row in rows]})


@require_user
@require_GET
def requests(request):
    return json_ok({"items": _user_request_items(DownloadRequest.objects.filter(user=request.user).order_by("-id")[:200])})


@require_user
@require_GET
def quota(request):
    products = Product.objects.filter(status="published").order_by("name")
    items = []
    for product in products:
        used = Download.objects.filter(product=product, user=request.user).exists()
        approved = DownloadRequest.objects.filter(product=product, user=request.user, status="approved", consumed_at__isnull=True).exists()
        pending = DownloadRequest.objects.filter(product=product, user=request.user, status="pending").exists()
        items.append({
            "product_id": product.pk, "product_name": product.name, "product_slug": product.slug,
            "product_version": product.version, "used_first_download": used,
            "has_unused_approved_request": approved, "has_pending_request": pending,
            "remaining_downloads": 1 if (not used or approved) else 0,
        })
    return json_ok({"items": items})


@require_GET
def download(request, key):
    admin = get_admin_context(request)
    if not request.user.is_authenticated and not admin:
        return json_error("login required before download", status=401)
    try:
        pkg_id = int(request.GET.get("pkg")) if request.GET.get("pkg") else None
    except ValueError:
        pkg_id = None
    product, file_info = resolve_file(key, bool(admin), pkg_id)
    if not product or not file_info:
        return HttpResponseNotFound()
    try:
        with transaction.atomic():
            from .services import account_download
            error = account_download(request, product, request.user if request.user.is_authenticated else None, file_info, pkg_id)
            if error:
                return error
    except Exception:
        raise
    return stream_file(file_info["path"], file_info["name"], request)


@require_user
@require_POST
def request_download(request, key):
    try:
        body = read_json(request)
    except InvalidJSON:
        body = {}
    product = Product.objects.filter(pk=int(key) if key.isdigit() else None).first() if key.isdigit() else Product.objects.filter(slug=key).first()
    if not product or product.status != "published":
        return json_error("product not found", status=404)
    if not Download.objects.filter(product=product, user=request.user).exists():
        return json_error("user has not consumed first download yet")
    if DownloadRequest.objects.filter(product=product, user=request.user, status="pending").exists():
        return json_error("request already pending", status=409)
    DownloadRequest.objects.create(user=request.user, product=product, reason=str(body.get("reason") or "").strip()[:1000], created_at=now_iso())
    return json_ok({"ok": True, "message": "request submitted"})


@require_admin(level=2)
def admin_requests(request):
    if request.method != "GET":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET"])
    status = request.GET.get("status", "pending")
    if status not in {"pending", "approved", "rejected", "all"}:
        status = "pending"
    query = DownloadRequest.objects.select_related("user", "product").order_by("-id")
    if status != "all":
        query = query.filter(status=status)
    rows = query[:300]
    return json_ok({"items": [{
        "id": row.pk, "user_id": row.user_id, "username": row.user.username,
        "product_id": row.product_id, "product_name": row.product.name, "product_slug": row.product.slug,
        "reason": row.reason, "status": row.status, "review_note": row.review_note,
        "created_at": row.created_at, "reviewed_at": row.reviewed_at,
        "reviewed_by": row.reviewed_by, "consumed_at": row.consumed_at,
    } for row in rows]})


@require_admin(level=2)
@require_POST
def review_request(request, request_id, decision):
    try:
        body = read_json(request)
    except InvalidJSON:
        body = {}
    row = DownloadRequest.objects.filter(pk=request_id).first()
    if not row:
        return json_error("request not found", status=404)
    if row.status != "pending":
        return json_error("request already reviewed", status=409)
    row.status = decision
    row.review_note = str(body.get("note") or "").strip()[:1000]
    row.reviewed_at = now_iso()
    row.reviewed_by = request.kflow_admin["username"]
    row.save(update_fields=["status", "review_note", "reviewed_at", "reviewed_by"])
    return json_ok({"ok": True, "status": decision})


@require_admin()
@require_POST
def upload_session_create(request, product_id):
    try:
        body = read_json(request)
        size = int(body.get("size", 0))
    except (InvalidJSON, TypeError, ValueError):
        return json_error("invalid upload session request")
    admin = request.kflow_admin
    original = safe_filename(body.get("filename", ""))
    platform = str(body.get("platform", "")).strip()
    architecture = str(body.get("architecture", "")).strip()
    if Path(original).suffix.lower() not in ALLOWED_EXTENSIONS:
        return json_error("unsupported package format")
    if platform not in {"Windows", "macOS", "Linux"}:
        return json_error("platform required, must be one of: Windows, macOS, Linux")
    if architecture not in {"x64", "ARM64"}:
        return json_error("architecture required, must be one of: x64, ARM64")
    if size <= 0:
        return json_error("file size is required")
    if size > effective_limit_bytes(admin["admin_level"]):
        return json_error(f"file too large for lv{admin['admin_level']}", status=413)
    product = Product.objects.filter(pk=product_id).first()
    if not product:
        return json_error("product not found", status=404)
    if admin["admin_level"] == 1 and product.created_by != admin["username"]:
        return json_error("lv1 can only upload to own products", status=403)
    upload_id = secrets.token_hex(16)
    directory = settings.BASE_DIR / "uploads" / ".chunk-sessions" / upload_id
    directory.mkdir(parents=True, exist_ok=False)
    UploadSession.objects.create(
        upload_id=upload_id, product_id=product_id, username=admin["username"], level=admin["admin_level"],
        original=original, size=size, count=(size + CHUNK_UPLOAD_SIZE - 1) // CHUNK_UPLOAD_SIZE,
        platform=platform, architecture=architecture, expires_at=time.time() + CHUNK_UPLOAD_TTL_SECONDS,
        expected_sha256=str(body.get("sha256") or "").strip().lower() or None, created_at=now_iso(),
    )
    session = UploadSession.objects.get(upload_id=upload_id)
    return json_ok({"upload_id": upload_id, "chunk_size": CHUNK_UPLOAD_SIZE, "chunk_count": session.count})


@require_admin()
@require_POST
def upload_chunk(request, upload_id, index):
    session = UploadSession.objects.filter(upload_id=upload_id, username=request.kflow_admin["username"]).first()
    if not session or session.expires_at <= time.time():
        return json_error("upload session not found or expired", status=404)
    if index < 0 or index >= session.count:
        return json_error("invalid chunk index")
    expected = min(CHUNK_UPLOAD_SIZE, session.size - index * CHUNK_UPLOAD_SIZE)
    if request.body.__len__() != expected:
        return json_error("chunk size mismatch", status=409)
    directory = settings.BASE_DIR / "uploads" / ".chunk-sessions" / upload_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{index:08d}.part").write_bytes(request.body)
    session.written = sum(p.stat().st_size for p in directory.glob("*.part"))
    session.expires_at = time.time() + CHUNK_UPLOAD_TTL_SECONDS
    session.save(update_fields=["written", "expires_at"])
    return json_ok()


@require_admin()
@require_POST
def upload_complete(request, upload_id):
    session = UploadSession.objects.filter(upload_id=upload_id, username=request.kflow_admin["username"]).first()
    if not session or session.expires_at <= time.time():
        return json_error("upload session not found or expired", status=404)
    directory = settings.BASE_DIR / "uploads" / ".chunk-sessions" / upload_id
    if any(not (directory / f"{index:08d}.part").is_file() for index in range(session.count)):
        return json_error("upload incomplete", status=409)
    target = settings.BASE_DIR / "uploads" / f"p{session.product_id}-{int(time.time())}-{secrets.token_hex(4)}{Path(session.original).suffix.lower()}"
    temporary = target.with_suffix(target.suffix + ".tmp")
    digest = hashlib.sha256()
    total = 0
    try:
        with temporary.open("wb") as output:
            for index in range(session.count):
                with (directory / f"{index:08d}.part").open("rb") as source:
                    while block := source.read(1024 * 1024):
                        output.write(block); digest.update(block); total += len(block)
        sha = digest.hexdigest()
        if total != session.size:
            return json_error("merged file size mismatch", status=409)
        if session.expected_sha256 and sha != session.expected_sha256:
            return json_error("sha256 mismatch", status=409)
        product = Product.objects.filter(pk=session.product_id).first()
        if not product:
            return json_error("product not found", status=404)
        if session.level == 1 and product.created_by != request.kflow_admin["username"]:
            return json_error("lv1 can only upload to own products", status=403)
        temporary.replace(target)
        relative = str(target.relative_to(settings.BASE_DIR)).replace("\\", "/")
        current = now_iso()
        with transaction.atomic():
            Product.objects.filter(pk=product.pk).update(file_name=session.original, file_path=relative, file_size=total, file_sha256=sha, updated_at=current)
            from apps.catalog.models import AdminUploadEvent
            AdminUploadEvent.objects.update_or_create(admin_username=request.kflow_admin["username"], product=product, defaults={"uploaded_at": current, "file_size": total})
            max_sort = ProductPackage.objects.filter(product=product).order_by("-sort_order").values_list("sort_order", flat=True).first()
            ProductPackage.objects.create(product=product, platform=session.platform, architecture=session.architecture, file_name=session.original, file_path=relative, file_size=total, file_sha256=sha, sort_order=(-1 if max_sort is None else max_sort) + 1, created_at=current, updated_at=current)
            session.delete()
        shutil.rmtree(directory, ignore_errors=True)
        return json_ok({"ok": True, "productId": product.pk, "fileName": session.original, "fileSize": total, "fileSha256": sha, "adminLevel": session.level, "autoPromoted": False})
    except OSError:
        temporary.unlink(missing_ok=True)
        return json_error("failed to merge upload chunks", status=500)
    finally:
        temporary.unlink(missing_ok=True)
