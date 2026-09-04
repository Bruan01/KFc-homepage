# pyright: reportMissingImports=false
"""Core Django views."""
import json
import re
import urllib.error
import urllib.request

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

NEWAPI_BASE = getattr(settings, "NEWAPI_BASE_URL", "").rstrip("/")
NEWAPI_ACCESS_TOKEN = getattr(settings, "NEWAPI_ACCESS_TOKEN", "")
NEWAPI_USER_ID = getattr(settings, "NEWAPI_USER_ID", "")
_PROXY_TIMEOUT = 8  # seconds

_STATUS_FIELDS = (
    "system_name",
)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_IP_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\w.])")


def _redact_public_text(value) -> str:
    text = str(value or "")
    text = _URL_RE.sub("[地址已隐藏]", text)
    return _IP_RE.sub("[地址已隐藏]", text)


def _upstream_error(data: dict, code: int) -> dict:
    message = data.get("message") or data.get("error") or "上游服务暂时不可用"
    return {"success": False, "error": _redact_public_text(message), "data": {}}



@require_GET
def health(request):
    return JsonResponse(
        {"ok": True, "time": timezone.now().isoformat()},
        json_dumps_params={"ensure_ascii": False},
    )


def _newapi_get(path: str) -> tuple[dict, int]:
    """Fetch a JSON endpoint from the NewAPI service."""
    if not NEWAPI_BASE:
        return {"error": "状态服务尚未配置"}, 503
    url = f"{NEWAPI_BASE}{path}"
    headers = {"User-Agent": "KFlow-StatusPage/1.0"}
    if NEWAPI_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {NEWAPI_ACCESS_TOKEN}"
    if NEWAPI_USER_ID:
        headers["New-Api-User"] = NEWAPI_USER_ID
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_PROXY_TIMEOUT) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except Exception:
            body = {"error": str(exc)}
        return body, exc.code
    except Exception as exc:
        return {"error": str(exc)}, 502


@require_GET
def newapi_status(request):
    """Return the public, redacted NewAPI service status."""
    data, code = _newapi_get("/api/status")
    if code >= 400:
        return JsonResponse(_upstream_error(data, code), status=code, json_dumps_params={"ensure_ascii": False})

    source = data.get("data", data)
    public = {field: source.get(field) for field in _STATUS_FIELDS if field in source}
    announcements = source.get("announcements") or []
    public["announcements"] = [
        {
            "type": item.get("type", "info"),
            "content": _redact_public_text(item.get("content")),
        }
        for item in announcements
        if isinstance(item, dict) and item.get("content")
    ]
    return JsonResponse(
        {"success": bool(data.get("success", True)), "data": public},
        status=code,
        json_dumps_params={"ensure_ascii": False},
    )


@require_GET
def newapi_pricing(request):
    """Return the public model catalogue used by NewAPI's pricing page."""
    data, code = _newapi_get("/api/pricing")
    if code >= 400:
        return JsonResponse(_upstream_error(data, code), status=code, json_dumps_params={"ensure_ascii": False})

    models = []
    for item in data.get("data", []) if isinstance(data.get("data"), list) else []:
        if not isinstance(item, dict) or not item.get("model_name"):
            continue
        models.append(
            {
                "name": _redact_public_text(item["model_name"]),
                "description": _redact_public_text(item.get("description")),
                "icon": _redact_public_text(item.get("icon")),
                "tags": _redact_public_text(item.get("tags")),
                "endpoints": item.get("supported_endpoint_types") or [],
            }
        )
    models.sort(key=lambda item: item["name"].lower())
    return JsonResponse(
        {"success": bool(data.get("success", True)), "data": {"models": models, "total": len(models)}},
        status=code,
        json_dumps_params={"ensure_ascii": False},
    )


@require_GET
def newapi_models(request):
    """Return a flat, public model list without upstream channel details."""
    data, code = _newapi_get("/api/models")
    if code >= 400:
        return JsonResponse(_upstream_error(data, code), status=code, json_dumps_params={"ensure_ascii": False})

    source = data.get("data", {})
    models = []
    if isinstance(source, dict):
        for names in source.values():
            if not isinstance(names, list):
                continue
            for name in names:
                if name:
                    models.append({"name": _redact_public_text(name)})
    elif isinstance(source, list):
        for item in source:
            if isinstance(item, dict) and item.get("name"):
                models.append({"name": _redact_public_text(item["name"])})
            elif item:
                models.append({"name": _redact_public_text(item)})

    models.sort(key=lambda item: item["name"].lower())
    return JsonResponse(
        {"success": bool(data.get("success", True)), "data": {"models": models, "total": len(models)}},
        status=code,
        json_dumps_params={"ensure_ascii": False},
    )


@require_GET
def newapi_channels(request):
    """Return public channel health fields only; never expose keys or base URLs."""
    data, code = _newapi_get("/api/channel/")
    if code >= 400:
        return JsonResponse(_upstream_error(data, code), status=code, json_dumps_params={"ensure_ascii": False})

    items = data.get("data", {}).get("items", [])
    channels = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        model_text = str(item.get("models") or "")
        models = [name.strip() for name in model_text.split(",") if name.strip()]
        channels.append(
            {
                "id": item.get("id"),
                "name": _redact_public_text(item.get("name")) or "未命名渠道",
                "status": item.get("status") == 1,
                "test_model": _redact_public_text(item.get("test_model")),
                "model_count": len(models),
                "weight": item.get("weight"),
                "priority": item.get("priority"),
            }
        )
    return JsonResponse(
        {"success": bool(data.get("success", True)), "data": {"channels": channels, "total": len(channels)}},
        status=code,
        json_dumps_params={"ensure_ascii": False},
    )
