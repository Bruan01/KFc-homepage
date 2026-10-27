"""Bearer 令牌鉴权：终端不带 Cookie，因此不参与 CSRF。"""
from __future__ import annotations

from functools import wraps
from http import HTTPStatus

from .models import STATUS_ACTIVE, TerminalDevice
from .services import hash_token


def _bearer_token(request) -> str:
    header = request.META.get("HTTP_AUTHORIZATION", "") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def resolve_device(request):
    """返回 (device, error_response)；两者只有一个非空。"""
    from apps.core.responses import json_error

    raw = _bearer_token(request)
    if not raw or len(raw) < 16:
        return None, json_error("device token required", status=HTTPStatus.UNAUTHORIZED)
    device = (
        TerminalDevice.objects.select_related("user")
        .filter(token_hash=hash_token(raw), status=STATUS_ACTIVE)
        .first()
    )
    if device is None:
        return None, json_error("invalid device token", status=HTTPStatus.UNAUTHORIZED)
    if device.user_id is None:
        return None, json_error("device not bound", status=HTTPStatus.FORBIDDEN)
    return device, None


def require_device(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        device, error = resolve_device(request)
        if error is not None:
            return error
        request.terminal_device = device
        return view(request, *args, **kwargs)

    return wrapped
