"""KFlow role and administrator-level permission helpers."""
from __future__ import annotations

from functools import wraps
from http import HTTPStatus

from django.conf import settings

from apps.accounts.models import AdminAccount
from .responses import json_error


def get_admin_context(request):
    username = request.session.get("admin_username", "")
    if username:
        return {
            "username": username,
            "admin_level": int(request.session.get("admin_level", 1)),
            "is_super": bool(request.session.get("admin_is_super", False)),
        }
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None
    if user.username == settings.ADMIN_USERNAME:
        return {"username": user.username, "admin_level": 3, "is_super": True}
    admin = AdminAccount.objects.filter(username=user.username).first()
    if not admin:
        return None
    return {
        "username": admin.username,
        "admin_level": int(admin.admin_level or 1),
        "is_super": bool(admin.is_super),
    }


def require_user(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return json_error("user login required", status=HTTPStatus.UNAUTHORIZED)
        return view(request, *args, **kwargs)
    return wrapped


def require_admin(level=1, *, super_only=False):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            admin = get_admin_context(request)
            if not admin:
                return json_error("unauthorized", status=HTTPStatus.UNAUTHORIZED)
            if super_only and not admin["is_super"]:
                return json_error("super admin required", status=HTTPStatus.FORBIDDEN)
            if int(admin["admin_level"]) < int(level):
                return json_error(f"lv{level} admin required", status=HTTPStatus.FORBIDDEN)
            request.kflow_admin = admin
            return view(request, *args, **kwargs)
        return wrapped
    return decorator
