from __future__ import annotations

import base64
import binascii
import hashlib
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.points.services import account_payload, apply_ledger, get_rules
from .config import ensure_default_provider
from .models import ImageGenerationJob, ImagingProvider, ImagingProviderAttempt

ALLOWED_SIZES = {"1024x1024", "1536x1024", "1024x1536"}
ALLOWED_QUALITIES = {"low", "medium", "high"}
ALLOWED_FORMATS = {"png", "jpeg", "webp"}
MAX_RESPONSE_BYTES = 40 * 1024 * 1024
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_OPEN_SECONDS = 5 * 60
ERROR_MAX_LENGTH = 1000


class ImagingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class ImageProviderError(RuntimeError):
    pass


def _now() -> datetime:
    return timezone.now()


def _read_response(response) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_RESPONSE_BYTES:
        raise ImageProviderError("显影服务返回的图片过大。")
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ImageProviderError("显影服务返回的图片过大。")
    return data


def _provider_error(response) -> str:
    try:
        payload = json.loads(response.read(64 * 1024).decode("utf-8", errors="replace"))
        error = payload.get("error", payload)
        if isinstance(error, dict):
            return str(error.get("message") or error.get("error") or response.reason)
        return str(error)
    except (ValueError, OSError):
        return str(getattr(response, "reason", "请求失败"))


def _sanitize_error(value: object, provider: ImagingProvider | None = None) -> str:
    message = str(value or "请求失败").replace("\n", " ").replace("\r", " ").strip()
    if provider and provider.api_key:
        message = message.replace(provider.api_key, "[redacted]")
    return message[:ERROR_MAX_LENGTH]


def _request_provider_image(job: ImageGenerationJob, provider: ImagingProvider) -> bytes:
    api_key = provider.api_key
    if not api_key:
        raise ImageProviderError("该显影服务未配置 API Key。")
    payload = json.dumps(
        {
            "model": provider.model,
            "prompt": job.prompt,
            "size": job.size,
            "quality": job.quality,
            "output_format": job.output_format,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{provider.base_url}/images/generations",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=provider.timeout_seconds) as response:
            raw = _read_response(response)
    except urllib.error.HTTPError as exc:
        raise ImageProviderError(f"显影服务请求失败：{_provider_error(exc)}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ImageProviderError(f"无法连接显影服务 {provider.name}（{provider.base_url}）。") from exc

    try:
        image = (json.loads(raw.decode("utf-8")).get("data") or [])[0]
    except (ValueError, IndexError, KeyError, TypeError) as exc:
        raise ImageProviderError("显影服务返回了无法识别的图像响应。") from exc
    encoded = image.get("b64_json") if isinstance(image, dict) else None
    if encoded:
        try:
            return base64.b64decode(encoded)
        except (ValueError, binascii.Error) as exc:
            raise ImageProviderError("显影服务返回的图片数据无法保存。") from exc
    image_url = image.get("url") if isinstance(image, dict) else None
    if image_url:
        try:
            with urllib.request.urlopen(str(image_url), timeout=min(provider.timeout_seconds, 120)) as response:
                return _read_response(response)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ImageProviderError("已生成图片，但下载生成结果失败。") from exc
    raise ImageProviderError("显影服务响应中没有可用的图片内容。")


def _eligible_providers_locked() -> list[ImagingProvider]:
    now = _now()
    return list(
        ImagingProvider.objects.select_for_update()
        .filter(enabled=True)
        .exclude(api_key="")
        .exclude(base_url="")
        .exclude(model="")
        .filter(circuit_open_until__isnull=True)
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


def _record_failure(provider_id: int, error: str) -> None:
    with transaction.atomic():
        provider = ImagingProvider.objects.select_for_update().filter(pk=provider_id).first()
        if not provider:
            return
        provider.consecutive_failures += 1
        provider.last_failure_at = _now()
        provider.last_error = _sanitize_error(error, provider)
        if provider.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
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
                duration_ms=int((monotonic() - started) * 1000),
                error=error,
            )
            _record_failure(provider.pk, error)
            last_error = error
            continue
        _record_attempt(
            job=job,
            provider=provider,
            attempt_number=attempt_number,
            status=ImagingProviderAttempt.SUCCEEDED,
            started_at=started_at,
            duration_ms=int((monotonic() - started) * 1000),
        )
        _record_success(provider.pk)
        return content, provider
    if last_provider:
        ImageGenerationJob.objects.filter(pk=job.pk).update(provider=last_provider)
    if len(candidate_ids) == 1 and last_error:
        raise ImageProviderError(last_error)
    raise ImageProviderError("所有已启用显影服务暂时不可用。")


def test_provider_connection(provider: ImagingProvider) -> dict:
    """Validate the configured endpoint without creating a billable user job."""
    probe = ImageGenerationJob(prompt="服务连接测试", size="1024x1024", quality="low", output_format="png")
    started_at = _now()
    started = monotonic()
    try:
        _request_provider_image(probe, provider)
    except ImageProviderError as exc:
        error = _sanitize_error(exc, provider)
        _record_failure(provider.pk, error)
        return {"ok": False, "error": error, "durationMs": int((monotonic() - started) * 1000)}
    _record_success(provider.pk)
    return {"ok": True, "durationMs": int((monotonic() - started) * 1000), "testedAt": started_at.isoformat()}


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


def create_generation(*, user, payload: dict) -> tuple[ImageGenerationJob, bool, dict]:
    prompt, size, quality, output_format = _payload_values(payload)
    key = _idempotency_key(payload.get("idempotencyKey") or payload.get("idempotency_key"))
    rules = get_rules()
    cost = max(0, int(rules["image_generation_default_cost"]))
    with transaction.atomic():
        existing = ImageGenerationJob.objects.filter(user=user, idempotency_key=key).first()
        if existing:
            return existing, False, account_payload(user)
        job = ImageGenerationJob.objects.create(
            user=user,
            prompt=prompt,
            size=size,
            quality=quality,
            output_format=output_format,
            points_cost=cost,
            idempotency_key=key,
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
        filename = f"{job.user_id}/{job.created_at:%Y/%m}/{job.pk}.{job.output_format}"
        job.image.save(filename, ContentFile(content), save=False)
        job.image_sha256 = hashlib.sha256(content).hexdigest()
        with transaction.atomic():
            current = ImageGenerationJob.objects.select_for_update().get(pk=job.pk)
            if current.status != ImageGenerationJob.GENERATING:
                if job.image.name:
                    job.image.storage.delete(job.image.name)
                return
            current.provider = provider
            current.image.name = job.image.name
            current.image_sha256 = job.image_sha256
            current.status = ImageGenerationJob.COMPLETED
            current.completed_at = _now()
            current.error = ""
            current.save(update_fields=["provider", "image", "image_sha256", "status", "completed_at", "error", "updated_at"])
    except ImageProviderError as exc:
        if job.image.name:
            job.image.storage.delete(job.image.name)
        _refund_and_fail(job_id, str(exc))
    except Exception:
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
    filename = Path(job.image.name).name if job.image.name else None
    return {
        "id": str(job.pk),
        "status": job.status,
        "prompt": job.prompt,
        "size": job.size,
        "quality": job.quality,
        "output_format": job.output_format,
        "points_cost": int(job.points_cost),
        "provider": job.provider.name if job.provider_id else None,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "image_url": f"/api/imaging/generations/{job.pk}/image" if job.status == ImageGenerationJob.COMPLETED and job.image else None,
        "download_url": f"/api/imaging/generations/{job.pk}/download" if job.status == ImageGenerationJob.COMPLETED and job.image else None,
        "filename": filename,
        "error": job.error or None,
    }
