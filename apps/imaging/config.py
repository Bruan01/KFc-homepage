from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import SystemSetting
from .models import ImagingProvider

CONFIG_KEYS = {
    "base_url": "imaging.cpa.base_url",
    "api_key": "imaging.cpa.api_key",
    "model": "imaging.cpa.model",
    "timeout_seconds": "imaging.cpa.timeout_seconds",
}
DEFAULT_PROVIDER_NAME = "默认 CPA 服务"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_TIMEOUT_SECONDS = 360
MIN_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 900
MIN_WEIGHT = 1
MAX_WEIGHT = 1000
MIN_PRIORITY = -10000
MAX_PRIORITY = 10000
ERROR_MAX_LENGTH = 1000


class ImagingConfigError(ValueError):
    pass


def _local_api_key() -> str | None:
    config_path = Path(os.getenv("CPA_CONFIG_PATH", "/Users/mac/Desktop/CPA-Manager-Plus-main/config.yaml")).expanduser()
    if not config_path.is_file():
        return None
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


def _stored_values() -> dict[str, str]:
    keys = tuple(CONFIG_KEYS.values())
    return dict(SystemSetting.objects.filter(setting_key__in=keys).values_list("setting_key", "setting_value"))


def _validate_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ImagingConfigError("CPA Base URL 必须是合法的 HTTP/HTTPS 地址")
    return normalized


def _validate_model(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 120:
        raise ImagingConfigError("模型名称不能为空且不能超过 120 个字符")
    return normalized


def _validate_timeout(value) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise ImagingConfigError("请求超时时间必须是整数") from exc
    if not MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS:
        raise ImagingConfigError(f"请求超时时间必须在 {MIN_TIMEOUT_SECONDS}～{MAX_TIMEOUT_SECONDS} 秒之间")
    return timeout


def _validate_name(value: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 120:
        raise ImagingConfigError("服务名称不能为空且不能超过 120 个字符")
    return name


def _validate_weight(value) -> int:
    try:
        weight = int(value)
    except (TypeError, ValueError) as exc:
        raise ImagingConfigError("权重必须是整数") from exc
    if not MIN_WEIGHT <= weight <= MAX_WEIGHT:
        raise ImagingConfigError(f"权重必须在 {MIN_WEIGHT}～{MAX_WEIGHT} 之间")
    return weight


def _validate_priority(value) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError) as exc:
        raise ImagingConfigError("优先级必须是整数") from exc
    if not MIN_PRIORITY <= priority <= MAX_PRIORITY:
        raise ImagingConfigError(f"优先级必须在 {MIN_PRIORITY}～{MAX_PRIORITY} 之间")
    return priority


def _validate_enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    if value in {0, "0", "false", "False", "off", ""}:
        return False
    if value in {1, "1", "true", "True", "on"}:
        return True
    raise ImagingConfigError("启用状态必须是布尔值")


def get_legacy_provider_config() -> dict:
    stored = _stored_values()
    base_url = stored.get(CONFIG_KEYS["base_url"]) or getattr(settings, "CPA_BASE_URL", "http://127.0.0.1:8317/v1")
    model = stored.get(CONFIG_KEYS["model"]) or DEFAULT_MODEL
    timeout = stored.get(CONFIG_KEYS["timeout_seconds"]) or DEFAULT_TIMEOUT_SECONDS
    if CONFIG_KEYS["api_key"] in stored:
        api_key = stored[CONFIG_KEYS["api_key"]]
    else:
        api_key = str(getattr(settings, "CPA_API_KEY", "") or os.getenv("CPA_API_KEY", "")).strip() or _local_api_key() or ""
    return {
        "base_url": _validate_base_url(base_url),
        "api_key": str(api_key or "").strip(),
        "model": _validate_model(model),
        "timeout_seconds": _validate_timeout(timeout),
    }


# Retained for existing imports and third-party configuration readers.
def get_provider_config() -> dict:
    return get_legacy_provider_config()


def _legacy_setting_is_present() -> bool:
    return bool(_stored_values()) or bool(getattr(settings, "CPA_BASE_URL", "")) or bool(getattr(settings, "CPA_API_KEY", "")) or bool(os.getenv("CPA_API_KEY")) or bool(_local_api_key())


@transaction.atomic
def ensure_default_provider() -> ImagingProvider | None:
    existing = ImagingProvider.objects.order_by("id").first()
    if existing:
        return existing
    if not _legacy_setting_is_present():
        return None
    config = get_legacy_provider_config()
    return ImagingProvider.objects.create(
        name=DEFAULT_PROVIDER_NAME,
        enabled=True,
        base_url=config["base_url"],
        api_key=config["api_key"],
        model=config["model"],
        timeout_seconds=config["timeout_seconds"],
        weight=1,
        priority=100,
    )


def _health_payload(provider: ImagingProvider) -> dict:
    now = timezone.now()
    if not provider.enabled:
        status = "disabled"
    elif not provider.api_key or not provider.base_url or not provider.model:
        status = "unconfigured"
    elif provider.circuit_open_until and provider.circuit_open_until > now:
        status = "circuit_open"
    elif provider.circuit_open_until:
        status = "recovering"
    else:
        status = "available"
    return {
        "status": status,
        "circuitOpenUntil": provider.circuit_open_until.isoformat() if provider.circuit_open_until else None,
        "lastSuccessAt": provider.last_success_at.isoformat() if provider.last_success_at else None,
        "lastFailureAt": provider.last_failure_at.isoformat() if provider.last_failure_at else None,
        "consecutiveFailures": provider.consecutive_failures,
        "lastError": provider.last_error or None,
    }


def provider_payload(provider: ImagingProvider) -> dict:
    key = provider.api_key or ""
    return {
        "id": provider.pk,
        "name": provider.name,
        "enabled": provider.enabled,
        "baseUrl": provider.base_url,
        "model": provider.model,
        "timeoutSeconds": provider.timeout_seconds,
        "weight": provider.weight,
        "priority": provider.priority,
        "apiKeyConfigured": bool(key),
        "apiKeyMasked": f"••••{key[-4:]}" if key else "未配置",
        "createdAt": provider.created_at.isoformat(),
        "updatedAt": provider.updated_at.isoformat(),
        **_health_payload(provider),
    }


def list_provider_payloads() -> list[dict]:
    ensure_default_provider()
    return [provider_payload(provider) for provider in ImagingProvider.objects.order_by("priority", "id")]


def _provider_defaults(payload: dict, *, current: ImagingProvider | None = None) -> dict:
    legacy = get_legacy_provider_config() if current is None else None
    fields = {
        "name": _validate_name(payload.get("name", current.name if current else "")),
        "enabled": _validate_enabled(payload.get("enabled", current.enabled if current else True)),
        "base_url": _validate_base_url(payload.get("baseUrl", current.base_url if current else legacy["base_url"])),
        "model": _validate_model(payload.get("model", current.model if current else legacy["model"])),
        "timeout_seconds": _validate_timeout(payload.get("timeoutSeconds", current.timeout_seconds if current else legacy["timeout_seconds"])),
        "weight": _validate_weight(payload.get("weight", current.weight if current else 1)),
        "priority": _validate_priority(payload.get("priority", current.priority if current else 100)),
    }
    if current:
        fields["api_key"] = current.api_key
    else:
        fields["api_key"] = str(payload.get("apiKey") or legacy["api_key"] or "").strip()
    if bool(payload.get("clearApiKey")):
        fields["api_key"] = ""
    elif str(payload.get("apiKey") or "").strip():
        fields["api_key"] = str(payload["apiKey"]).strip()
    return fields


@transaction.atomic
def create_provider(payload: dict, updated_by: str) -> ImagingProvider:
    del updated_by  # Configuration audit timestamps are provided by the model itself.
    values = _provider_defaults(payload)
    if ImagingProvider.objects.filter(name=values["name"]).exists():
        raise ImagingConfigError("服务名称已存在")
    return ImagingProvider.objects.create(**values)


@transaction.atomic
def update_provider(provider: ImagingProvider, payload: dict, updated_by: str) -> ImagingProvider:
    del updated_by
    values = _provider_defaults(payload, current=provider)
    if ImagingProvider.objects.exclude(pk=provider.pk).filter(name=values["name"]).exists():
        raise ImagingConfigError("服务名称已存在")
    for field, value in values.items():
        setattr(provider, field, value)
    provider.save()
    return provider


@transaction.atomic
def recover_provider(provider: ImagingProvider) -> ImagingProvider:
    provider.consecutive_failures = 0
    provider.circuit_open_until = None
    provider.last_error = ""
    provider.save(update_fields=["consecutive_failures", "circuit_open_until", "last_error", "updated_at"])
    return provider


@transaction.atomic
def delete_provider(provider: ImagingProvider) -> None:
    provider.delete()


def provider_config_payload() -> dict:
    provider = ensure_default_provider()
    if provider:
        return provider_payload(provider)
    config = get_legacy_provider_config()
    key = config["api_key"]
    return {
        "baseUrl": config["base_url"],
        "model": config["model"],
        "timeoutSeconds": config["timeout_seconds"],
        "apiKeyConfigured": bool(key),
        "apiKeyMasked": f"••••{key[-4:]}" if key else "未配置",
    }


@transaction.atomic
def save_provider_config(payload: dict, updated_by: str) -> dict:
    """Compatibility writer for the old single-service settings endpoint."""
    provider = ensure_default_provider()
    if provider is None:
        values = _provider_defaults({"name": DEFAULT_PROVIDER_NAME, **payload})
        provider = ImagingProvider.objects.create(**values)
    else:
        update_provider(provider, {"name": provider.name, **payload}, updated_by)

    now = timezone.now().isoformat()
    for key, value in {
        CONFIG_KEYS["base_url"]: provider.base_url,
        CONFIG_KEYS["api_key"]: provider.api_key,
        CONFIG_KEYS["model"]: provider.model,
        CONFIG_KEYS["timeout_seconds"]: str(provider.timeout_seconds),
    }.items():
        SystemSetting.objects.update_or_create(
            setting_key=key,
            defaults={"setting_value": value, "updated_at": now, "updated_by": updated_by},
        )
    return provider_payload(provider)
