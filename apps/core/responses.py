"""Shared JSON response helpers."""
from __future__ import annotations

from http import HTTPStatus

from django.http import JsonResponse


def json_error(message: str, *, status: int = HTTPStatus.BAD_REQUEST, **extra) -> JsonResponse:
    payload = {"error": message}
    payload.update(extra)
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})


def json_ok(payload: dict | None = None, *, status: int = HTTPStatus.OK) -> JsonResponse:
    data = {"ok": True} if payload is None else payload
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})
