# pyright: reportMissingImports=false
"""Notification API views."""
from __future__ import annotations

from django.views.decorators.http import require_GET, require_POST

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_user
from apps.core.responses import json_error, json_ok

from .models import Notification
from .services import payload, unread_count


@require_user
def notifications(request):
    if request.method == "GET":
        flt = request.GET.get("filter", "all")
        try:
            limit = min(50, max(1, int(request.GET.get("limit", 30))))
        except ValueError:
            limit = 30
        qs = Notification.objects.filter(recipient=request.user)
        if flt == "unread":
            qs = qs.filter(is_read=False)
        rows = list(qs[:limit])
        return json_ok({
            "items": [payload(row) for row in rows],
            "unreadCount": unread_count(request.user),
        })
    from django.http import HttpResponseNotAllowed

    return HttpResponseNotAllowed(["GET"])


@require_user
@require_GET
def unread_count_view(request):
    return json_ok({"unreadCount": unread_count(request.user)})


@require_user
@require_POST
def mark_read(request):
    try:
        body = read_json(request)
        ids = [int(i) for i in (body.get("ids") or []) if str(i).strip().lstrip("-").isdigit()]
    except (InvalidJSON, TypeError, ValueError):
        return json_error("invalid json")
    if ids:
        Notification.objects.filter(recipient=request.user, id__in=ids).update(is_read=True)
    return json_ok({"ok": True, "unreadCount": unread_count(request.user)})


@require_user
@require_POST
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return json_ok({"ok": True, "unreadCount": 0})
