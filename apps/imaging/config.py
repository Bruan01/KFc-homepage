from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import SystemSetting

CONFIG_KEYS = {
    "base_url": "imaging.cpa.base_url",
    "api_key": "imaging.cpa.api_key",
    "model": "imaging.cpa.model",
    "timeout_seconds": "imaging.cpa.timeout_seconds",
}
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_TIMEOUT_SECONDS = 360
MIN_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 900


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


def get_provider_config() -> dict:
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


def provider_config_payload() -> dict:
    config = get_provider_config()
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
    current = get_provider_config()
    base_url = _validate_base_url(payload.get("baseUrl", current["base_url"]))
    model = _validate_model(payload.get("model", current["model"]))
    timeout = _validate_timeout(payload.get("timeoutSeconds", current["timeout_seconds"]))
    values = {
        CONFIG_KEYS["base_url"]: base_url,
        CONFIG_KEYS["model"]: model,
        CONFIG_KEYS["timeout_seconds"]: str(timeout),
    }
    if bool(payload.get("clearApiKey")):
        values[CONFIG_KEYS["api_key"]] = ""
    elif str(payload.get("apiKey") or "").strip():
        values[CONFIG_KEYS["api_key"]] = str(payload["apiKey"]).strip()
    now = timezone.now().isoformat()
    for key, value in values.items():
        SystemSetting.objects.update_or_create(
            setting_key=key,
            defaults={"setting_value": value, "updated_at": now, "updated_by": updated_by},
        )
    return provider_config_payload()
