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
from .config import ImagingConfigError, provider_config_payload, save_provider_config
from .models import ImageGenerationJob
from .services import ImagingError, create_generation, job_payload


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
    except ImagingError as exc:
        return json_error(exc.message, status=exc.status)
    response = job_payload(job)
    response["balance"] = account["balance"]
    response["created"] = created
    return json_ok(response, status=HTTPStatus.ACCEPTED if created else HTTPStatus.OK)


@require_user
@require_GET
def detail(request, job_id):
    job = ImageGenerationJob.objects.filter(pk=job_id, user=request.user).first()
    if not job:
        return json_error("generation job not found", status=HTTPStatus.NOT_FOUND)
    return json_ok(job_payload(job))


@require_user
@require_GET
def history(request):
    jobs = ImageGenerationJob.objects.filter(
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
