"""Middleware that upgrades still-valid legacy sessions into Django sessions."""
from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import login

from apps.accounts.models import AdminAccount, LegacySession, User


class LegacySessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._upgrade(request)
        return self.get_response(request)

    def _upgrade(self, request):
        if request.user.is_authenticated or request.session.get("admin_username"):
            return
        raw_tokens = [
            request.COOKIES.get(settings.SESSION_COOKIE_NAME, ""),
            request.COOKIES.get(settings.ADMIN_SESSION_COOKIE, ""),
        ]
        for token in filter(None, raw_tokens):
            legacy = LegacySession.objects.filter(token=token).first()
            if not legacy:
                continue
            if float(legacy.exp) < time.time():
                legacy.delete()
                continue
            if legacy.role == "user" and legacy.user_id:
                user = User.objects.filter(pk=legacy.user_id).first()
                if not user:
                    continue
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                self._set_admin_from_user(request, user)
                legacy.delete()
                return
            if legacy.role == "admin":
                request.session.cycle_key()
                request.session["admin_username"] = legacy.username
                request.session["admin_level"] = int(legacy.admin_level or 1)
                request.session["admin_is_super"] = bool(legacy.is_super)
                legacy.delete()
                return

    @staticmethod
    def _set_admin_from_user(request, user):
        if user.username == settings.ADMIN_USERNAME:
            request.session["admin_username"] = user.username
            request.session["admin_level"] = 3
            request.session["admin_is_super"] = True
            return
        admin = AdminAccount.objects.filter(username=user.username).first()
        if admin:
            request.session["admin_username"] = admin.username
            request.session["admin_level"] = int(admin.admin_level or 1)
            request.session["admin_is_super"] = bool(admin.is_super)
