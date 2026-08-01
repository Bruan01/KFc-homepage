from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.points.services import account_payload, apply_ledger, get_rules
from .models import ImageGenerationJob

ALLOWED_SIZES = {"1024x1024", "1536x1024", "1024x1536"}
ALLOWED_QUALITIES = {"low", "medium", "high"}
ALLOWED_FORMATS = {"png", "jpeg", "webp"}
MAX_RESPONSE_BYTES = 40 * 1024 * 1024


class ImagingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class ImageProviderError(RuntimeError):
    pass


def _now() -> datetime:
    return timezone.now()


def _api_key() -> str | None:
    key = str(getattr(settings, "CPA_API_KEY", "") or os.getenv("CPA_API_KEY", "")).strip()
    if key:
        return key
    config_path = Path(os.getenv("CPA_CONFIG_PATH", "/Users/mac/Desktop/CPA-Manager-Plus-main/config.yaml")).expanduser()
    if not config_path.is_file():
        return None
    # The fallback deliberately reads only the first scalar under api-keys. It
    # avoids adding a YAML dependency just to discover a local development key.
    try:
        in_api_keys = False
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "api-keys:":
                in_api_keys = True
                continue
            if in_api_keys and stripped.startswith("-"):
                candidate = stripped[1:].strip().strip("\"'")
                if candidate:
                    return candidate
            if in_api_keys and stripped and not line.startswith((" ", "\t")):
                break
    except OSError:
        return None
    return None


def _read_response(response) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_RESPONSE_BYTES:
        raise ImageProviderError("CPA 返回的图片过大。")
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ImageProviderError("CPA 返回的图片过大。")
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


def generate_image_bytes(job: ImageGenerationJob) -> bytes:
    api_key = _api_key()
    if not api_key:
        raise ImageProviderError("未找到 CPA_API_KEY，请配置生图服务密钥。")
    base_url = str(getattr(settings, "CPA_BASE_URL", "http://127.0.0.1:8317/v1")).rstrip("/")
    payload = json.dumps(
        {
            "model": "gpt-image-2",
            "prompt": job.prompt,
            "size": job.size,
            "quality": job.quality,
            "output_format": job.output_format,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/images/generations",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=360) as response:
            raw = _read_response(response)
    except urllib.error.HTTPError as exc:
        raise ImageProviderError(f"CPA 生图失败：{_provider_error(exc)}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ImageProviderError("无法连接本机 CPA 服务，请确认 8317 端口服务正在运行。") from exc

    try:
        image = (json.loads(raw.decode("utf-8")).get("data") or [])[0]
    except (ValueError, IndexError, KeyError, TypeError) as exc:
        raise ImageProviderError("CPA 返回了无法识别的图像响应。") from exc
    encoded = image.get("b64_json") if isinstance(image, dict) else None
    if encoded:
        try:
            return base64.b64decode(encoded)
        except (ValueError, binascii.Error) as exc:
            raise ImageProviderError("CPA 返回的图片数据无法保存。") from exc
    image_url = image.get("url") if isinstance(image, dict) else None
    if image_url:
        try:
            with urllib.request.urlopen(str(image_url), timeout=120) as response:
                return _read_response(response)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ImageProviderError("已生成图片，但下载生成结果失败。") from exc
    raise ImageProviderError("CPA 响应中没有可用的图片内容。")


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
        raise ImagingError("invalid output format")
    return prompt, size, quality, output_format


def _idempotency_key(user, value) -> str:
    key = str(value or "").strip()
    if not key:
        return uuid4().hex
    if len(key) < 8 or len(key) > 160:
        raise ImagingError("idempotency key must contain 8 to 160 characters")
    return key


def create_generation(*, user, payload: dict) -> tuple[ImageGenerationJob, bool, dict]:
    prompt, size, quality, output_format = _payload_values(payload)
    key = _idempotency_key(user, payload.get("idempotencyKey") or payload.get("idempotency_key"))
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


def process_generation(job_id) -> None:
    with transaction.atomic():
        job = ImageGenerationJob.objects.select_for_update().filter(pk=job_id).first()
        if not job or job.status != ImageGenerationJob.QUEUED:
            return
        job.status = ImageGenerationJob.GENERATING
        job.started_at = _now()
        job.save(update_fields=["status", "started_at", "updated_at"])
    try:
        content = generate_image_bytes(job)
        filename = f"{job.user_id}/{job.created_at:%Y/%m}/{job.pk}.{job.output_format}"
        job.image.save(filename, ContentFile(content), save=False)
        job.image_sha256 = hashlib.sha256(content).hexdigest()
        with transaction.atomic():
            current = ImageGenerationJob.objects.select_for_update().get(pk=job.pk)
            if current.status != ImageGenerationJob.GENERATING:
                if job.image.name:
                    job.image.storage.delete(job.image.name)
                return
            current.image.name = job.image.name
            current.image_sha256 = job.image_sha256
            current.status = ImageGenerationJob.COMPLETED
            current.completed_at = _now()
            current.error = ""
            current.save(update_fields=["image", "image_sha256", "status", "completed_at", "error", "updated_at"])
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
    for job_id in stale_ids:
        _refund_and_fail(job_id, "生成进程中断，任务已自动退款。")
    return len(stale_ids)


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
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "image_url": f"/api/imaging/generations/{job.pk}/image" if job.status == ImageGenerationJob.COMPLETED and job.image else None,
        "filename": filename,
        "error": job.error or None,
    }
