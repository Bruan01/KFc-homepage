"""Serve the existing static HTML application through Django."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from .permissions import get_admin_context

PAGE_MAP = {
    "": "index.html",
    "login": "user-login.html",
    "account": "account.html",
    "points": "points.html",
    "admin": "admin.html",
    "admin/bigscreen": "admin-bigscreen.html",
    "cardloom": "cardloom_official_website.html",
}


def _safe_static_path(relative):
    root = (settings.BASE_DIR / "static").resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise Http404 from exc
    if not target.is_file():
        raise Http404
    return target


def _file_response(target):
    content_type, _ = mimetypes.guess_type(str(target))
    response = FileResponse(target.open("rb"), content_type=content_type or "application/octet-stream")
    if target.suffix.lower() == ".html":
        response["Cache-Control"] = "no-cache"
    return response


@require_GET
def legacy_admin_redirect(request):
    return redirect("/login?next=/admin")


@require_GET
def page(request, page_path=""):
    if page_path in {"admin", "admin/bigscreen"} and not get_admin_context(request):
        return redirect(f"/login?next=/{page_path}")
    relative = PAGE_MAP.get(page_path)
    if relative is None:
        raise Http404
    return _file_response(_safe_static_path(relative))


@require_GET
def product_page(request, slug):
    return _file_response(_safe_static_path("product.html"))


@require_GET
def static_asset(request, asset_path):
    return _file_response(_safe_static_path(asset_path))


@require_GET
def material_file(request, asset_path):
    root = Path(settings.MATERIAL_ROOT).resolve()
    target = (root / asset_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return HttpResponseForbidden()
    if not target.is_file():
        raise Http404
    return _file_response(target)
