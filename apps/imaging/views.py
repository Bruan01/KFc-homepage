from __future__ import annotations

import json
import mimetypes
import uuid
from http import HTTPStatus
from pathlib import Path

from django.conf import settings
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
from .models import ImageGenerationJob, ImagingProvider, ImagingTemplate
from .prompt_templates import (
    TemplateError,
    admin_template_payload,
    create_template,
    list_admin_template_payloads,
    list_template_payloads,
    update_template,
)
from .services import ImagingError, create_generation, job_payload, test_provider_connection


TEMPLATE_COVER_MAX_BYTES = 5 * 1024 * 1024
TEMPLATE_COVER_TYPES = {
    "gif": "image/gif",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _template_cover_type(content):
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp"
    return ""


@ensure_csrf_cookie
@require_GET
def studio_page(request):
    if not request.user.is_authenticated:
        return HttpResponseRedirect("/login?next=/imaging")
    return render(request, "imaging/index.html", {"username": request.user.username})


@require_user
@require_GET
def templates(request):
    return json_ok({"items": list_template_payloads()})


@require_user
@require_GET
def template_cover(request, filename):
    root = (Path(settings.MEDIA_ROOT) / "imaging" / "template-covers").resolve()
    target = (root / filename).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return json_error("template cover not found", status=HTTPStatus.NOT_FOUND)
    extension = target.suffix.lower().lstrip(".")
    if extension not in TEMPLATE_COVER_TYPES or not target.is_file():
        return json_error("template cover not found", status=HTTPStatus.NOT_FOUND)
    try:
        handle = target.open("rb")
    except OSError:
        return json_error("template cover unavailable", status=HTTPStatus.NOT_FOUND)
    response = FileResponse(handle, content_type=TEMPLATE_COVER_TYPES[extension])
    response["Cache-Control"] = "private, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_user
@require_POST
def create(request):
    try:
        if request.content_type.startswith("multipart/form-data"):
            try:
                payload = json.loads(request.POST.get("payload") or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise InvalidJSON("invalid json") from exc
            if not isinstance(payload, dict):
                raise InvalidJSON("invalid json")
            reference_files = request.FILES.getlist("references")
        else:
            payload = read_json(request)
            reference_files = []
        job, created, account = create_generation(
            user=request.user, payload=payload, reference_files=reference_files,
        )
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


@require_admin(level=3, super_only=True)
@require_GET
def admin_templates(request):
    return json_ok({"items": list_admin_template_payloads()})


@require_admin(level=3, super_only=True)
@require_POST
def admin_template_cover_upload(request):
    uploaded = request.FILES.get("cover")
    if not uploaded:
        return json_error("请选择要上传的封面图片")
    if uploaded.size > TEMPLATE_COVER_MAX_BYTES:
        return json_error("封面图片不能超过 5MB", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    content = uploaded.read(TEMPLATE_COVER_MAX_BYTES + 1)
    if not content:
        return json_error("封面图片不能为空")
    if len(content) > TEMPLATE_COVER_MAX_BYTES:
        return json_error("封面图片不能超过 5MB", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    image_type = _template_cover_type(content)
    if not image_type:
        return json_error("仅支持 PNG、JPEG、WebP 或 GIF 图片")

    directory = Path(settings.MEDIA_ROOT) / "imaging" / "template-covers"
    filename = f"{uuid.uuid4().hex}.{image_type}"
    target = directory / filename
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(content)
    except OSError:
        target.unlink(missing_ok=True)
        return json_error("封面图片保存失败", status=HTTPStatus.INTERNAL_SERVER_ERROR)
    return json_ok(
        {
            "url": f"/uploads/imaging/template-covers/{filename}",
            "filename": filename,
            "size": len(content),
        },
        status=HTTPStatus.CREATED,
    )


@require_admin(level=3, super_only=True)
@require_POST
def admin_template_create(request):
    try:
        row = create_template(read_json(request))
    except InvalidJSON:
        return json_error("invalid json")
    except TemplateError as exc:
        return json_error(str(exc), status=HTTPStatus.BAD_REQUEST)
    return json_ok({"item": admin_template_payload(row)}, status=HTTPStatus.CREATED)


@require_admin(level=3, super_only=True)
def admin_template_detail(request, template_id):
    row = ImagingTemplate.objects.filter(pk=template_id).first()
    if not row:
        return json_error("imaging template not found", status=HTTPStatus.NOT_FOUND)
    if request.method == "PATCH":
        try:
            row = update_template(row, read_json(request))
        except InvalidJSON:
            return json_error("invalid json")
        except TemplateError as exc:
            return json_error(str(exc), status=HTTPStatus.BAD_REQUEST)
        return json_ok({"item": admin_template_payload(row)})
    if request.method == "DELETE":
        if row.is_system:
            return json_error("内置模板不能删除，请停用或复制后再修改", status=HTTPStatus.CONFLICT)
        row.delete()
        return json_ok({"ok": True, "deletedId": template_id})
    from django.http import HttpResponseNotAllowed
    return HttpResponseNotAllowed(["PATCH", "DELETE"])
