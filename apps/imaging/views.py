# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportArgumentType=false, reportCallIssue=false
from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus

from django.db import transaction
from pathlib import Path
from uuid import UUID

from django.http import (
    FileResponse,
    HttpResponse,
    HttpResponseNotAllowed,
    HttpResponseNotModified,
    HttpResponseRedirect,
)
from django.utils.http import http_date, parse_http_date_safe
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin, require_user
from apps.core.responses import json_error, json_ok
from apps.points.services import PointsError, apply_ledger, ensure_account
from apps.points.models import PointLedger
from .constants import ORIGINAL_DOWNLOAD_COST
from .config import (
    ImagingConfigError,
    create_provider,
    delete_provider,
    list_provider_payloads,
    provider_config_payload,
    provider_payload,
    recover_provider,
    save_provider_config,
    update_provider,
)
from .models import ImageGenerationJob, ImagingProvider
from .services import ImagingError, create_generation, job_payload, test_provider_connection


@ensure_csrf_cookie
@require_GET
def studio_page(request):
    if not request.user.is_authenticated:
        return HttpResponseRedirect("/login?next=/imaging")
    return render(request, "imaging/index.html", {"username": request.user.username})


@require_user
@require_POST
def create(request):
    try:
        payload = read_json(request)
        job, created, account = create_generation(user=request.user, payload=payload)
    except InvalidJSON:
        return json_error("invalid json")
    except Exception as exc:
        if isinstance(exc, PointsError):
            message = {
                "insufficient points": "积分不足，请先获取足够积分后再生成。",
                "points account frozen": "积分账户已冻结，暂时无法生成图片。",
            }.get(exc.message, exc.message or "积分操作失败。")
            return json_error(message, status=exc.status)
        if isinstance(exc, ImagingError):
            return json_error(exc.message, status=exc.status)
        raise
    response = job_payload(job)
    response["balance"] = account["balance"]
    response["created"] = created
    return json_ok(response, status=HTTPStatus.ACCEPTED if created else HTTPStatus.OK)


@require_user
@require_GET
def detail(request, job_id):
    job = ImageGenerationJob.objects.select_related("provider").filter(pk=job_id, user=request.user).first()
    if not job:
        return json_error("generation job not found", status=HTTPStatus.NOT_FOUND)
    return json_ok(job_payload(job))


@require_user
@require_GET
def history(request):
    jobs = ImageGenerationJob.objects.select_related("provider").filter(
        user=request.user,
        status=ImageGenerationJob.COMPLETED,
    ).exclude(image="").order_by("-created_at")[:12]
    return HttpResponse(
        json.dumps([job_payload(job) for job in jobs], ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )


@require_user
@require_GET
def image(request, job_id):
    job = ImageGenerationJob.objects.filter(pk=job_id, user=request.user, status=ImageGenerationJob.COMPLETED).first()
    if not job or not job.image:
        return json_error("image not found", status=HTTPStatus.NOT_FOUND)
    return _serve_image(request, job, "inline")


@require_user
@require_POST
def download(request, job_id):
    """Charge one point per confirmed download; retries share an idempotency key."""
    job = ImageGenerationJob.objects.filter(pk=job_id, user=request.user, status=ImageGenerationJob.COMPLETED).first()
    if not job or not job.original_image:
        return json_error("此图片未保留未经压缩的原图，无法下载。", status=HTTPStatus.NOT_FOUND)
    try:
        payload = read_json(request)
        if not isinstance(payload, dict) or payload.get("confirmed") is not True:
            return json_error("请先确认支付 1 积分下载原图。")
        request_key = str(UUID(str(payload.get("idempotency_key", ""))))
    except (InvalidJSON, ValueError, TypeError, AttributeError):
        return json_error("下载请求无效，请关闭弹窗后重试。")
    # Read before charging: missing or unreadable files must never cost points.
    try:
        with job.original_image.open("rb") as original:
            content = original.read()
        if not content:
            raise OSError("empty original")
    except OSError:
        return json_error("原图文件暂时不可用，未扣除积分。", status=HTTPStatus.NOT_FOUND)
    try:
        with transaction.atomic():
            # Lock the account before checking retries, serializing concurrent requests.
            account = ensure_account(request.user)
            if account.status != "active":
                raise PointsError("points account frozen", HTTPStatus.FORBIDDEN)
            ledger_key = f"image_download:{request.user.pk}:{request_key}"
            existing = PointLedger.objects.filter(idempotency_key=ledger_key).first()
            if existing and existing.reference_id != str(job.pk):
                return json_error("下载请求已用于其他图片，请重新确认。", status=HTTPStatus.CONFLICT)
            apply_ledger(
                user=request.user, event_type="image_download",
                points_delta=-ORIGINAL_DOWNLOAD_COST,
                idempotency_key=ledger_key, description="显影原图下载",
                reference_type="image_generation", reference_id=job.pk,
            )
            account.refresh_from_db()
            balance = account.balance
    except PointsError as exc:
        message = {"insufficient points": "积分不足，下载原图需要 1 积分。",
                   "points account frozen": "积分账户已冻结，暂时无法下载原图。"}.get(exc.message, "积分操作失败，请稍后重试。")
        return json_error(message, status=exc.status)
    filename = Path(job.original_image.name).name
    response = HttpResponse(content, content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Points-Balance"] = str(balance)
    return response


def _modified_timestamp(modified):
    try:
        return round(modified.timestamp())
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


def _is_not_modified(request, etag, modified):
    if etag and request.headers.get("If-None-Match") == etag:
        return True
    if modified:
        raw = request.headers.get("If-Modified-Since")
        timestamp = parse_http_date_safe(raw) if raw else None
        modified_timestamp = _modified_timestamp(modified)
        if timestamp is not None and modified_timestamp is not None and modified_timestamp <= timestamp:
            return True
    return False


def _serve_image(request, job, disposition):
    etag = f'"{job.image_sha256}"' if job.image_sha256 else None
    modified = job.completed_at or job.updated_at
    if _is_not_modified(request, etag, modified):
        response = HttpResponseNotModified()
        response["Cache-Control"] = "private, max-age=86400"
        if etag:
            response["ETag"] = etag
        if modified:
            modified_timestamp = _modified_timestamp(modified)
            if modified_timestamp is not None:
                response["Last-Modified"] = http_date(modified_timestamp)
        return response
    try:
        handle = job.image.open("rb")
    except OSError:
        return json_error("image file unavailable", status=HTTPStatus.NOT_FOUND)
    content_type = mimetypes.guess_type(job.image.name)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    filename = job.image.name.rsplit("/", 1)[-1]
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=86400"
    if etag:
        response["ETag"] = etag
    if modified:
        modified_timestamp = _modified_timestamp(modified)
        if modified_timestamp is not None:
            response["Last-Modified"] = http_date(modified_timestamp)
    return response


@require_admin(level=3, super_only=True)
def admin_settings(request):
    """Old single-provider endpoint retained for current deployments."""
    if request.method == "GET":
        return json_ok({"item": provider_config_payload()})
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        payload = read_json(request)
        result = save_provider_config(payload, request.kflow_admin["username"])
    except InvalidJSON:
        return json_error("invalid json")
    except ImagingConfigError as exc:
        return json_error(str(exc))
    return json_ok({"ok": True, "item": result})


@require_admin(level=3, super_only=True)
@require_GET
def admin_providers(request):
    return json_ok({"items": list_provider_payloads()})


@require_admin(level=3, super_only=True)
@require_POST
def admin_provider_create(request):
    try:
        provider = create_provider(read_json(request), request.kflow_admin["username"])
    except InvalidJSON:
        return json_error("invalid json")
    except ImagingConfigError as exc:
        return json_error(str(exc))
    return json_ok({"item": provider_payload(provider)}, status=HTTPStatus.CREATED)


@require_admin(level=3, super_only=True)
def admin_provider_detail(request, provider_id):
    provider = ImagingProvider.objects.filter(pk=provider_id).first()
    if not provider:
        return json_error("imaging provider not found", status=HTTPStatus.NOT_FOUND)
    if request.method == "PATCH":
        try:
            provider = update_provider(provider, read_json(request), request.kflow_admin["username"])
        except InvalidJSON:
            return json_error("invalid json")
        except ImagingConfigError as exc:
            return json_error(str(exc))
        return json_ok({"item": provider_payload(provider)})
    if request.method == "DELETE":
        delete_provider(provider)
        return json_ok({"ok": True, "deletedId": provider_id})
    return HttpResponseNotAllowed(["PATCH", "DELETE"])


@require_admin(level=3, super_only=True)
@require_POST
def admin_provider_test(request, provider_id):
    provider = ImagingProvider.objects.filter(pk=provider_id).first()
    if not provider:
        return json_error("imaging provider not found", status=HTTPStatus.NOT_FOUND)
    result = test_provider_connection(provider)
    provider.refresh_from_db()
    status = HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_GATEWAY
    return json_ok({"item": provider_payload(provider), "result": result}, status=status)


@require_admin(level=3, super_only=True)
@require_POST
def admin_provider_recover(request, provider_id):
    provider = ImagingProvider.objects.filter(pk=provider_id).first()
    if not provider:
        return json_error("imaging provider not found", status=HTTPStatus.NOT_FOUND)
    return json_ok({"item": provider_payload(recover_provider(provider))})
