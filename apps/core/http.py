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
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""
