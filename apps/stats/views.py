# pyright: reportMissingImports=false
"""Admin-facing visit statistics."""
from __future__ import annotations

from django.views.decorators.http import require_GET

from apps.core.permissions import require_admin
from apps.core.responses import json_ok

from . import services


@require_admin()
@require_GET
def visits(request):
    try:
        days = int(request.GET.get("days", ""))
    except (TypeError, ValueError):
        days = None
    return json_ok(services.summary(request.GET.get("range"), days))
