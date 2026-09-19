# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.points.services import account_payload, apply_ledger, get_rules
from .config import ensure_default_provider
from .constants import ORIGINAL_DOWNLOAD_COST
from .models import ImageGenerationJob, ImageGenerationReference, ImagingProvider, ImagingProviderAttempt
from .prompt_templates import TemplateError, get_template, render_template
from .providers.openai import ImageProviderError, OpenAIImagesClient, normalize_openai_api_base_url

ALLOWED_SIZES = {"1024x1024", "1536x1024", "1024x1536"}
ALLOWED_QUALITIES = {"low", "medium", "high"}
ALLOWED_FORMATS = {"png", "jpeg", "webp"}
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_OPEN_SECONDS = 5 * 60
ERROR_MAX_LENGTH = 1000
JPEG_QUALITY = 85
WEBP_QUALITY = 82
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_REFERENCE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ImagingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> datetime:
    return timezone.now()


def _elapsed_ms(started: float) -> int:
    try:
        return max(0, round((monotonic() - started) * 1000))
    except (OverflowError, ValueError):
        return 0


def _configured_cost(rules: dict) -> int:
    try:
        return max(0, int(rules.get("image_generation_default_cost", 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _cache_key(user_id, prompt: str, size: str, quality: str, output_format: str) -> str:
    normalized = json.dumps(
        [str(user_id), prompt, size, quality, output_format],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _compressed_image(content: bytes, output_format: str) -> bytes:
    """Validate and optimize an image without changing its dimensions or requested format."""
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            source_format = (source.format or "").lower()
            image = source.copy()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageProviderError("显影服务返回了无效的图片数据。") from exc

    output = io.BytesIO()
    try:
        if output_format == "png":
            image.save(output, format="PNG", optimize=True)
        elif output_format == "jpeg":
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "white")
                if image.mode in {"RGBA", "LA"}:
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        elif output_format == "webp":
            image.save(output, format="WEBP", quality=WEBP_QUALITY, method=6)
        else:
            raise ImageProviderError("无法压缩不支持的图片格式。")
    except (OSError, ValueError) as exc:
        raise ImageProviderError("图片压缩失败，请稍后重试。") from exc
    optimized = output.getvalue()
    format_matches = source_format in ({"jpg", "jpeg"} if output_format == "jpeg" else {output_format})
    if format_matches and len(optimized) >= len(content):
        return content
    return optimized


def _find_cached_job(*, user, cache_key: str) -> ImageGenerationJob | None:
    threshold = _now() - timedelta(days=getattr(settings, "IMAGING_CACHE_DAYS", 30))
    candidates = ImageGenerationJob.objects.filter(
        user=user,
        cache_key=cache_key,
        status=ImageGenerationJob.COMPLETED,
        completed_at__gte=threshold,
    ).exclude(image="").order_by("-completed_at")
    for candidate in candidates:
        try:
            if (candidate.image.storage.exists(candidate.image.name)
                    and candidate.original_image
                    and candidate.original_image.storage.exists(candidate.original_image.name)):
                return candidate
        except OSError:
            continue
    return None


def _sanitize_error(value: object, provider: ImagingProvider | None = None) -> str:
    message = str(value or "请求失败").replace("\n", " ").replace("\r", " ").strip()
    if provider and provider.api_key:
        message = message.replace(provider.api_key, "[redacted]")
    message = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+|(?:api[_-]?key|token)\s*[:=]\s*)[^\s,;&]+",
        r"\1[redacted]",
        message,
    )
    message = re.sub(
        r"(?i)([?&](?:api[_-]?key|access[_-]?token|token)=)[^&\s]+",
        r"\1[redacted]",
        message,
    )
    return message[:ERROR_MAX_LENGTH]


def _request_provider_image(job: ImageGenerationJob, provider: ImagingProvider) -> bytes:
    try:
        client = OpenAIImagesClient(provider.base_url, provider.api_key, provider.timeout_seconds)
    except ValueError as exc:
        raise ImageProviderError(str(exc), category="configuration", retryable=False) from exc
    return client.generate(
        model=provider.model,
        prompt=job.prompt,
        size=job.size,
        quality=job.quality,
        output_format=job.output_format,
        references=list(job.references.all()),
    )


def _eligible_providers_locked() -> list[ImagingProvider]:
    now = _now()
    return list(
        ImagingProvider.objects.select_for_update()
        .filter(enabled=True)
        .exclude(api_key="")
        .exclude(base_url="")
        .exclude(model="")
        .filter(Q(circuit_open_until__isnull=True) | Q(circuit_open_until__lte=now))
        .order_by("priority", "id")
    )


def select_provider_candidates() -> list[int]:
    """Persist one smooth weighted round-robin selection and return failover order."""
    ensure_default_provider()
    with transaction.atomic():
        providers = _eligible_providers_locked()
        seen: set[int] = set()
        providers = [provider for provider in providers if not (provider.pk in seen or seen.add(provider.pk))]
        if not providers:
            return []
        total_weight = sum(provider.weight for provider in providers)
        for provider in providers:
            provider.schedule_current_weight += provider.weight
        selected = max(providers, key=lambda provider: (provider.schedule_current_weight, -provider.priority, -provider.pk))
        selected.schedule_current_weight -= total_weight
        ImagingProvider.objects.bulk_update(providers, ["schedule_current_weight", "updated_at"])
        others = sorted(
            (provider for provider in providers if provider.pk != selected.pk),
            key=lambda provider: (-provider.schedule_current_weight, provider.priority, provider.pk),
        )
        return [selected.pk, *(provider.pk for provider in others)]


def _record_success(provider_id: int) -> None:
    with transaction.atomic():
        provider = ImagingProvider.objects.select_for_update().filter(pk=provider_id).first()
        if not provider:
            return
        provider.consecutive_failures = 0
        provider.circuit_open_until = None
        provider.last_success_at = _now()
        provider.last_error = ""
        provider.save(update_fields=["consecutive_failures", "circuit_open_until", "last_success_at", "last_error", "updated_at"])


def _record_failure(provider_id: int, error: ImageProviderError | str) -> None:
    with transaction.atomic():
        provider = ImagingProvider.objects.select_for_update().filter(pk=provider_id).first()
        if not provider:
            return
        category = error.category if isinstance(error, ImageProviderError) else "provider_error"
        if category != "request_rejected":
            provider.consecutive_failures += 1
        provider.last_failure_at = _now()
        provider.last_error = _sanitize_error(error, provider)
        permanent_categories = {"authentication", "configuration", "endpoint_not_found", "model_not_available"}
        if category in permanent_categories:
            provider.consecutive_failures = max(provider.consecutive_failures, CIRCUIT_FAILURE_THRESHOLD)
        if category != "request_rejected" and provider.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
            provider.circuit_open_until = _now() + timedelta(seconds=CIRCUIT_OPEN_SECONDS)
        provider.save(
            update_fields=[
                "consecutive_failures",
                "last_failure_at",
                "last_error",
                "circuit_open_until",
                "updated_at",
            ]
        )


def _record_attempt(
    *,
    job: ImageGenerationJob,
    provider: ImagingProvider,
    attempt_number: int,
    status: str,
    started_at: datetime,
    duration_ms: int,
    error: str = "",
) -> None:
    ImagingProviderAttempt.objects.create(
        job=job,
        provider=provider,
        provider_name=provider.name,
        attempt_number=attempt_number,
        status=status,
        error=_sanitize_error(error, provider),
        started_at=started_at,
        completed_at=_now(),
        duration_ms=max(0, duration_ms),
    )


def generate_image_bytes(job: ImageGenerationJob) -> tuple[bytes, ImagingProvider]:
    candidate_ids = select_provider_candidates()
    if not candidate_ids:
        raise ImageProviderError("所有已启用显影服务暂时不可用。")
    last_provider: ImagingProvider | None = None
    last_error = ""
    for attempt_number, provider_id in enumerate(candidate_ids, start=1):
        provider = ImagingProvider.objects.filter(pk=provider_id).first()
        if not provider:
            continue
        last_provider = provider
        started_at = _now()
        started = monotonic()
        try:
            content = _request_provider_image(job, provider)
        except ImageProviderError as exc:
            error = _sanitize_error(exc, provider)
            _record_attempt(
                job=job,
                provider=provider,
                attempt_number=attempt_number,
                status=ImagingProviderAttempt.FAILED,
                started_at=started_at,
                duration_ms=_elapsed_ms(started),
                error=error,
            )
            _record_failure(provider.pk, exc)
            last_error = error
            continue
        _record_attempt(
            job=job,
            provider=provider,
            attempt_number=attempt_number,
            status=ImagingProviderAttempt.SUCCEEDED,
            started_at=started_at,
            duration_ms=_elapsed_ms(started),
        )
        _record_success(provider.pk)
        return content, provider
    if last_provider:
        ImageGenerationJob.objects.filter(pk=job.pk).update(provider=last_provider)
    if len(candidate_ids) == 1 and last_error:
        raise ImageProviderError(last_error)
    raise ImageProviderError("所有已启用显影服务暂时不可用。")


def test_provider_connection(provider: ImagingProvider) -> dict:
    """Verify authentication and model access without making a billable image request."""
    started_at = _now()
    started = monotonic()
    try:
        client = OpenAIImagesClient(provider.base_url, provider.api_key, provider.timeout_seconds)
        result = client.check_model(provider.model)
    except (ImageProviderError, ValueError) as exc:
        if not isinstance(exc, ImageProviderError):
            exc = ImageProviderError(str(exc), category="configuration", retryable=False)
        error = _sanitize_error(exc, provider)
        payload = exc.diagnostic_payload()
        payload["error"] = error
        try:
            base_url = normalize_openai_api_base_url(provider.base_url)
        except ValueError:
            base_url = ""
        return {
            "ok": False,
            "billable": False,
            "model": provider.model,
            "authenticated": (
                True if exc.category == "model_not_available"
                else False if exc.category == "authentication"
                else None
            ),
            "modelAvailable": False if exc.category == "model_not_available" else None,
            "modelsEndpoint": f"{base_url}/models" if base_url else None,
            "imageGenerationEndpoint": f"{base_url}/images/generations" if base_url else None,
            "durationMs": _elapsed_ms(started),
            "testedAt": started_at.isoformat(),
            **payload,
        }
    return {
        "ok": True,
        "billable": False,
        "model": provider.model,
        "durationMs": _elapsed_ms(started),
        "testedAt": started_at.isoformat(),
        **result,
    }


def _payload_values(payload: dict) -> tuple[str, str, str, str]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or len(prompt) > 4000:
        raise ImagingError("prompt must contain 1 to 4000 characters")
    size = str(payload.get("size") or "1024x1024").strip()
    quality = str(payload.get("quality") or "low").strip()
    output_format = str(payload.get("output_format") or payload.get("outputFormat") or "png").strip()
    if size not in ALLOWED_SIZES:
        raise ImagingError("invalid image size")
    if quality not in ALLOWED_QUALITIES:
        raise ImagingError("invalid image quality")
    if output_format not in ALLOWED_FORMATS:
        raise ImagingError("invalid image format")
    return prompt, size, quality, output_format


def _idempotency_key(value) -> str:
    key = str(value or "").strip()
    if not key:
        return uuid4().hex
    if len(key) < 8 or len(key) > 160:
        raise ImagingError("idempotency key must contain 8 to 160 characters")
    return key


def _generation_values(payload: dict) -> tuple[str, str, str, str, str, str, str]:
    """Build a server-owned prompt when a curated template was selected."""
    template_key = str(payload.get("templateKey") or payload.get("template_key") or "").strip()
    if template_key:
        try:
            template, prompt, values = render_template(
                template_key,
                payload.get("templateValues") or payload.get("template_values"),
            )
        except TemplateError as exc:
            raise ImagingError(str(exc)) from exc
        extra_prompt = str(payload.get("extraPrompt") or payload.get("extra_prompt") or "").strip()
        if len(extra_prompt) > 800:
            raise ImagingError("补充要求不能超过800个字符")
        if extra_prompt:
            prompt = f"{prompt}\nAdditional preference: {extra_prompt}"
        if len(prompt) > 4000:
            raise ImagingError("模板生成的提示词过长")
        original_prompt = "\n".join(
            f"{field.label}：{values[field.key]}"
            for field in template.fields
            if values.get(field.key)
        )
        if extra_prompt:
            original_prompt = f"{original_prompt}\n补充要求：{extra_prompt}"
        _, size, quality, output_format = _payload_values({**payload, "prompt": prompt})
        return prompt, size, quality, output_format, original_prompt, template.key, template.name
    prompt, size, quality, output_format = _payload_values(payload)
    return prompt, size, quality, output_format, prompt, "", ""


def _validate_reference_files(template_key: str, reference_files) -> list:
    """Validate uploaded references against the selected template policy."""
    files = [item for item in (reference_files or []) if item and getattr(item, "size", 0)]
    if not template_key:
        if files:
            raise ImagingError("只有选择支持参考图的模板后才能上传图片")
        return []
    try:
        template = get_template(template_key)
    except TemplateError as exc:
        raise ImagingError(str(exc)) from exc
    maximum = int(template.reference_max_count or 0)
    if template.reference_required and not files:
        raise ImagingError("请至少上传一张参考图片")
    if len(files) > 10:
        raise ImagingError("最多上传10张参考图片")
    if maximum and len(files) > maximum:
        raise ImagingError(f"最多上传{maximum}张参考图片")
    for uploaded in files:
        content_type = (getattr(uploaded, "content_type", "") or "").lower()
        if content_type not in ALLOWED_REFERENCE_CONTENT_TYPES:
            raise ImagingError("参考图片仅支持 JPG、PNG 或 WebP 格式")
        if int(getattr(uploaded, "size", 0) or 0) > MAX_REFERENCE_IMAGE_BYTES:
            raise ImagingError("单张参考图片不能超过10MB")
    return files


def create_generation(*, user, payload: dict, reference_files=None) -> tuple[ImageGenerationJob, bool, dict]:
    prompt, size, quality, output_format, original_prompt, template_key, template_name = _generation_values(payload)
    reference_files = _validate_reference_files(template_key, reference_files)
    key = _idempotency_key(payload.get("idempotencyKey") or payload.get("idempotency_key"))
    cache_key = "" if reference_files else _cache_key(user.pk, prompt, size, quality, output_format)
    rules = get_rules()
    cost = _configured_cost(rules)
    with transaction.atomic():
        existing = ImageGenerationJob.objects.filter(user=user, idempotency_key=key).first()
        if existing:
            return existing, False, account_payload(user)
        cached = None if reference_files else _find_cached_job(user=user, cache_key=cache_key)
        job = ImageGenerationJob.objects.create(
            user=user,
            prompt=prompt,
            original_prompt=original_prompt,
            template_key=template_key,
            template_name=template_name,
            size=size,
            quality=quality,
            output_format=output_format,
            points_cost=cost,
            idempotency_key=key,
            cache_key=cache_key,
            cache_hit=bool(cached),
            cache_source=cached,
            provider=cached.provider if cached else None,
            image=cached.image.name if cached else "",
            original_image=cached.original_image.name if cached else "",
            image_sha256=cached.image_sha256 if cached else "",
            original_bytes=cached.original_bytes if cached else 0,
            stored_bytes=cached.stored_bytes if cached else 0,
            status=ImageGenerationJob.COMPLETED if cached else ImageGenerationJob.QUEUED,
            completed_at=_now() if cached else None,
        )
        for uploaded in reference_files:
            ImageGenerationReference.objects.create(
                job=job,
                image=uploaded,
                original_name=str(getattr(uploaded, "name", "reference"))[:255],
                content_type=(getattr(uploaded, "content_type", "") or "")[:100],
                file_size=int(getattr(uploaded, "size", 0) or 0),
            )
        ledger, _ = apply_ledger(
            user=user,
            event_type="image_generation",
            points_delta=-cost,
            idempotency_key=f"image_generation:{user.pk}:{key}",
            description=f"显影图片生成：{prompt[:80]}",
            reference_type="image_generation",
            reference_id=job.pk,
        )
        job.point_ledger = ledger
        job.save(update_fields=["point_ledger", "updated_at"])
        balance = account_payload(user)
        if not cached:
            transaction.on_commit(lambda: enqueue_generation(job.pk))
    return job, True, balance


def _refund_and_fail(job_id, message: str) -> None:
    with transaction.atomic():
        job = ImageGenerationJob.objects.select_for_update().filter(pk=job_id).first()
        if not job or job.status in {ImageGenerationJob.COMPLETED, ImageGenerationJob.FAILED}:
            return
        if job.points_cost and job.point_ledger_id:
            apply_ledger(
                user=job.user,
                event_type="image_generation_refund",
                points_delta=job.points_cost,
                idempotency_key=f"image_generation_refund:{job.pk}",
                description="显影生成失败自动退款",
                reference_type="image_generation",
                reference_id=job.pk,
                allow_frozen=True,
            )
        job.status = ImageGenerationJob.FAILED
        job.error = message[:4000]
        job.completed_at = _now()
        job.save(update_fields=["status", "error", "completed_at", "updated_at"])


def _requeue_interrupted(job_id) -> bool:
    with transaction.atomic():
        job = ImageGenerationJob.objects.select_for_update().filter(pk=job_id).first()
        if not job or job.status != ImageGenerationJob.GENERATING:
            return False
        job.status = ImageGenerationJob.QUEUED
        job.started_at = None
        job.error = ""
        job.save(update_fields=["status", "started_at", "error", "updated_at"])
        return True


def process_generation(job_id) -> None:
    with transaction.atomic():
        job = ImageGenerationJob.objects.select_for_update().filter(pk=job_id).first()
        if not job or job.status != ImageGenerationJob.QUEUED:
            return
        job.status = ImageGenerationJob.GENERATING
        job.started_at = _now()
        job.save(update_fields=["status", "started_at", "updated_at"])
    try:
        content, provider = generate_image_bytes(job)
        original_bytes = len(content)
        original_content = content
        content = _compressed_image(content, job.output_format)
        with Image.open(io.BytesIO(original_content)) as original:
            original_format = original.format.lower()
        job.original_image.save(f"{job.pk}.{original_format}", ContentFile(original_content), save=False)
        filename = f"{job.user_id}/{job.created_at:%Y/%m}/{job.pk}.{job.output_format}"
        job.image.save(filename, ContentFile(content), save=False)
        job.image_sha256 = hashlib.sha256(content).hexdigest()
        job.original_bytes = original_bytes
        job.stored_bytes = len(content)
        with transaction.atomic():
            current = ImageGenerationJob.objects.select_for_update().get(pk=job.pk)
            if current.status != ImageGenerationJob.GENERATING:
                if job.image.name:
                    job.image.storage.delete(job.image.name)
                if job.original_image.name:
                    job.original_image.storage.delete(job.original_image.name)
                return
            current.provider = provider
            current.original_image.name = job.original_image.name
            current.image.name = job.image.name
            current.image_sha256 = job.image_sha256
            current.original_bytes = job.original_bytes
            current.stored_bytes = job.stored_bytes
            current.status = ImageGenerationJob.COMPLETED
            current.completed_at = _now()
            current.error = ""
            current.save(
                update_fields=[
                    "provider", "image", "original_image", "image_sha256", "original_bytes", "stored_bytes",
                    "status", "completed_at", "error", "updated_at",
                ]
            )
    except ImageProviderError as exc:
        if job.original_image.name:
            job.original_image.storage.delete(job.original_image.name)
        if job.image.name:
            job.image.storage.delete(job.image.name)
        _refund_and_fail(job_id, str(exc))
    except Exception:
        if job.original_image.name:
            job.original_image.storage.delete(job.original_image.name)
        if job.image.name:
            job.image.storage.delete(job.image.name)
        _refund_and_fail(job_id, "生成过程发生未预期错误，请稍后重试。")


def enqueue_generation(job_id) -> None:
    thread = threading.Thread(target=process_generation, args=(job_id,), daemon=True, name=f"imaging-{job_id}")
    thread.start()


def recover_stale_jobs() -> int:
    threshold = _now() - timedelta(seconds=getattr(settings, "IMAGING_JOB_STALE_SECONDS", 1800))
    stale_ids = list(
        ImageGenerationJob.objects.filter(
            status=ImageGenerationJob.GENERATING,
            started_at__lt=threshold,
        ).values_list("pk", flat=True)
    )
    return sum(_requeue_interrupted(job_id) for job_id in stale_ids)


def job_payload(job: ImageGenerationJob) -> dict:
    filename = Path(job.original_image.name).name if job.original_image.name else None
    return {
        "id": str(job.pk),
        "status": job.status,
        "prompt": job.prompt,
        "original_prompt": job.original_prompt or job.prompt,
        "template_key": job.template_key or None,
        "template_name": job.template_name or None,
        "reference_count": job.references.count(),
        "size": job.size,
        "quality": job.quality,
        "output_format": job.output_format,
        "points_cost": job.points_cost or 0,
        "cache_hit": bool(job.cache_hit),
        "cache_source_id": str(job.cache_source_id) if job.cache_source_id else None,
        "original_bytes": job.original_bytes or 0,
        "stored_bytes": job.stored_bytes or 0,
        "provider": job.provider.name if job.provider_id else None,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "image_url": f"/api/imaging/generations/{job.pk}/image" if job.status == ImageGenerationJob.COMPLETED and job.image else None,
        "download_url": f"/api/imaging/generations/{job.pk}/download" if job.status == ImageGenerationJob.COMPLETED and job.original_image else None,
        "original_available": bool(job.original_image),
        "original_download_cost": ORIGINAL_DOWNLOAD_COST,
        "filename": filename,
        "error": job.error or None,
    }
