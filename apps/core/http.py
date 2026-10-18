"""HTTP parsing helpers shared by Django API views."""
from __future__ import annotations

import json


class InvalidJSON(ValueError):
    pass


def read_json(request) -> dict:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidJSON("invalid json") from exc
    if not isinstance(payload, dict):
        raise InvalidJSON("invalid json")
    return payload


def client_ip(request) -> str:
    """Best-effort client IP for rate limiting.

    ``X-Forwarded-For`` is client-controlled unless a reverse proxy overwrites it.
    Trusting it unconditionally lets anyone bypass the per-IP verification-code
    limit by sending a random header value on each request (mail bombing /
    bulk signup). Only honour it when the deployment is explicitly behind a
    trusted proxy (``TRUST_X_FORWARDED_FOR=1``); otherwise use the socket peer.
    """
    from django.conf import settings

    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""
