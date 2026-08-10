from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus

from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin, require_user
from apps.core.responses import json_error, json_ok
from apps.points.services import PointsError
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
    except PointsError as exc:
        message = {
            "insufficient points": "积分不足，请先获取足够积分后再生成。",
            "points account frozen": "积分账户已冻结，暂时无法生成图片。",
        }.get(exc.message, exc.message)
        return json_error(message, status=exc.status)
    except ImagingError as exc:
        return json_error(exc.message, status=exc.status)
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
    return _serve_image(job, "inline")


@require_user
@require_GET
def download(request, job_id):
    job = ImageGenerationJob.objects.filter(pk=job_id, user=request.user, status=ImageGenerationJob.COMPLETED).first()
    if not job or not job.image:
        return json_error("image not found", status=HTTPStatus.NOT_FOUND)
    return _serve_image(job, "attachment")


def _serve_image(job, disposition):
    try:
        handle = job.image.open("rb")
    except OSError:
        return json_error("image file unavailable", status=HTTPStatus.NOT_FOUND)
    content_type = mimetypes.guess_type(job.image.name)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    filename = job.image.name.rsplit("/", 1)[-1]
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_admin(level=3, super_only=True)
def admin_settings(request):
    """Old single-provider endpoint retained for current deployments."""
    if request.method == "GET":
        return json_ok({"item": provider_config_payload()})
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
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
    from django.http import HttpResponseNotAllowed
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
