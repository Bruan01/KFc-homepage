"""Django views for user and administrator authentication APIs."""
from __future__ import annotations

import secrets
from http import HTTPStatus

from django.conf import settings
from django.contrib.auth import logout
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef
from django.views.decorators.http import require_GET, require_POST

from apps.catalog.models import AdminUploadEvent
from apps.catalog.upload_limits import get_upload_limit_settings
from apps.core.http import InvalidJSON, client_ip, read_json
from apps.core.permissions import get_admin_context, require_admin, require_user
from apps.core.responses import json_error, json_ok
from apps.downloads.models import Download, DownloadRequest
from apps.points.services import award_registration
from .models import AdminAccount, AdminRegisterToken, User, UserSubscription
from .services import (
    AccountError,
    EMAIL_RE,
    admin_for_username,
    consume_verification_code,
    email_payload,
    issue_verification_code,
    mask_email,
    normalize_email,
    now_iso,
    start_admin_session,
    start_user_session,
    verify_admin_password,
    verify_user_password,
)


def _body(request):
    try:
        return read_json(request), None
    except InvalidJSON:
        return None, json_error("invalid json")


def _set_admin_cookie(response, request):
    if request.session.session_key:
        response.set_cookie(
            settings.ADMIN_SESSION_COOKIE,
            request.session.session_key,
            max_age=settings.SESSION_COOKIE_AGE,
            httponly=True,
            samesite="Lax",
            secure=settings.SESSION_COOKIE_SECURE,
            path="/",
        )
    return response


@require_POST
def verification_code(request):
    body, error = _body(request)
    if error:
        return error
    email = normalize_email(body.get("email"))
    purpose = str(body.get("purpose") or "").strip().lower()
    if purpose == "bind":
        if not request.user.is_authenticated:
            return json_error("login required", status=HTTPStatus.UNAUTHORIZED)
        if request.user.email and request.user.email_verified_at:
            return json_error("verified email already bound", status=HTTPStatus.CONFLICT)
        if User.objects.filter(email__iexact=email, email_verified_at__isnull=False).exclude(pk=request.user.pk).exists():
            return json_error("email already registered", status=HTTPStatus.CONFLICT)
    try:
        issue_verification_code(email, purpose, client_ip(request))
    except AccountError as exc:
        return json_error(exc.message, status=exc.status)
    return json_ok({"ok": True, "message": "If the email is eligible, a verification code has been sent."})


@require_POST
def register(request):
    body, error = _body(request)
    if error:
        return error
    username = str(body.get("username") or "").strip()
    email = normalize_email(body.get("email"))
    password = str(body.get("password") or "")
    code = str(body.get("code") or "").strip()
    invite_code = str(body.get("inviteCode") or body.get("invite_code") or "").strip()
    if not 3 <= len(username) <= 64:
        return json_error("username must be 3-64 characters")
    if not EMAIL_RE.fullmatch(email):
        return json_error("invalid email format")
    if len(password) < 8:
        return json_error("password must be at least 8 characters")
    if not code:
        return json_error("verification code required")

    try:
        with transaction.atomic():
            if username == settings.ADMIN_USERNAME or AdminAccount.objects.filter(username=username).exists():
                return json_error("username unavailable", status=HTTPStatus.CONFLICT)
            invite = None
            if invite_code:
                invite = AdminRegisterToken.objects.select_for_update().filter(
                    token=invite_code,
                    used_by_admin__isnull=True,
                ).first()
                if not invite:
                    return json_error("invalid or already used invite code")
                if AdminAccount.objects.filter(email__iexact=email).exists():
                    return json_error("admin email already registered", status=HTTPStatus.CONFLICT)

            user = User.objects.select_for_update().filter(username=username).first()
            if user and user.email_verified_at:
                return json_error("username already registered", status=HTTPStatus.CONFLICT)
            if user and not verify_user_password(user, password):
                return json_error("username already registered", status=HTTPStatus.CONFLICT)
            email_owner = User.objects.filter(email__iexact=email, email_verified_at__isnull=False).first()
            if email_owner and (not user or email_owner.pk != user.pk):
                return json_error("email already registered", status=HTTPStatus.CONFLICT)

            code_error = consume_verification_code(email, "register", code)
            if code_error:
                return json_error(code_error)

            verified_at = now_iso()
            if user:
                user.email = email
                user.email_verified_at = verified_at
                user.set_password(password)
                user.save(update_fields=["email", "email_verified_at", "password"])
            else:
                user = User(username=username, email=email, email_verified_at=verified_at, created_at=verified_at)
                user.set_password(password)
                user.save()

            if invite:
                admin = AdminAccount.objects.create(
                    username=username,
                    password_hash=user.password,
                    email=email,
                    created_at=verified_at,
                    created_by=invite.created_by,
                    is_super=0,
                    admin_level=int(invite.admin_level or 1),
                )
                invite.used_by_admin = admin
                invite.used_at = verified_at
                invite.save(update_fields=["used_by_admin", "used_at"])
            award_registration(user)
    except IntegrityError:
        return json_error("username or email already registered", status=HTTPStatus.CONFLICT)

    payload, is_admin = start_user_session(request, user)
    response = json_ok(payload)
    return _set_admin_cookie(response, request) if is_admin else response


def _admin_credentials(username, password):
    if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
        return {"username": username, "is_super": True, "admin_level": 3}
    admin = AdminAccount.objects.filter(username=username).first()
    if not admin or not verify_admin_password(admin, password):
        return None
    return {"username": admin.username, "is_super": bool(admin.is_super), "admin_level": int(admin.admin_level or 1)}


@require_POST
def user_login(request):
    body, error = _body(request)
    if error:
        return error
    method = str(body.get("method") or "username_password").strip().lower()
    user = None

    if method == "username_password":
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if not username or not password:
            return json_error("credentials required")
        user = User.objects.filter(username=username).first()
        registration_required = bool(user and verify_user_password(user, password) and not user.email_verified_at)
        if user and (registration_required or not verify_user_password(user, password)):
            user = None
        if not user:
            admin = _admin_credentials(username, password)
            if admin:
                payload = start_admin_session(request, admin)
                payload.update({"ok": True, "role": "admin", "is_admin": True})
                return _set_admin_cookie(json_ok(payload), request)
        if registration_required:
            return json_error("registration required", status=HTTPStatus.FORBIDDEN)
    elif method == "email_password":
        email = normalize_email(body.get("email"))
        password = str(body.get("password") or "")
        if not EMAIL_RE.fullmatch(email) or not password:
            return json_error("credentials required")
        user = User.objects.filter(email__iexact=email, email_verified_at__isnull=False).first()
        if not user or not verify_user_password(user, password):
            user = None
    elif method == "email_code":
        email = normalize_email(body.get("email"))
        code = str(body.get("code") or "").strip()
        if not EMAIL_RE.fullmatch(email) or not code:
            return json_error("credentials required")
        with transaction.atomic():
            user = User.objects.filter(email__iexact=email, email_verified_at__isnull=False).first()
            if not user:
                return json_error("invalid credentials", status=HTTPStatus.UNAUTHORIZED)
            code_error = consume_verification_code(email, "login", code)
            if code_error:
                return json_error(code_error, status=HTTPStatus.UNAUTHORIZED)
    else:
        return json_error("unsupported login method")

    if not user:
        return json_error("invalid credentials", status=HTTPStatus.UNAUTHORIZED)
    payload, is_admin = start_user_session(request, user)
    response = json_ok(payload)
    return _set_admin_cookie(response, request) if is_admin else response


@require_user
@require_POST
def email_bind(request):
    body, error = _body(request)
    if error:
        return error
    email = normalize_email(body.get("email"))
    code = str(body.get("code") or "").strip()
    current_password = str(body.get("currentPassword") or "")
    if not EMAIL_RE.fullmatch(email) or not code or not current_password:
        return json_error("email, code and current password required")

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not verify_user_password(user, current_password):
            return json_error("invalid current password", status=HTTPStatus.UNAUTHORIZED)
        if user.email and user.email_verified_at:
            return json_error("verified email already bound", status=HTTPStatus.CONFLICT)
        if User.objects.filter(email__iexact=email, email_verified_at__isnull=False).exclude(pk=user.pk).exists():
            return json_error("email already registered", status=HTTPStatus.CONFLICT)
        code_error = consume_verification_code(email, "bind", code)
        if code_error:
            return json_error(code_error)
        user.email = email
        user.email_verified_at = now_iso()
        user.set_password(current_password)
        user.save(update_fields=["email", "email_verified_at", "password"])
    return json_ok({"ok": True, "emailMasked": mask_email(email), "hasVerifiedEmail": True})


@require_POST
def user_logout(request):
    logout(request)
    response = json_ok()
    response.delete_cookie(settings.ADMIN_SESSION_COOKIE, path="/")
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return response


@require_GET
def user_me(request):
    if not request.user.is_authenticated:
        return json_ok({"loggedIn": False})
    return json_ok({
        "loggedIn": True,
        "username": request.user.username,
        "user_id": request.user.pk,
        **email_payload(request.user),
    })


@require_GET
def account_me(request):
    admin = get_admin_context(request)
    if admin:
        return json_ok({
            "loggedIn": True,
            "role": "admin",
            "username": admin["username"],
            "adminLevel": admin["admin_level"],
            "isSuper": admin["is_super"],
        })
    if not request.user.is_authenticated:
        return json_ok({"loggedIn": False, "role": "guest"})
    return json_ok({
        "loggedIn": True,
        "role": "user",
        "username": request.user.username,
        "user_id": request.user.pk,
        **email_payload(request.user),
    })


@require_POST
def admin_login(request):
    body, error = _body(request)
    if error:
        return error
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "").strip()
    if not username or not password:
        return json_error("credentials required")
    admin = _admin_credentials(username, password)
    if not admin:
        return json_error("invalid credentials", status=HTTPStatus.UNAUTHORIZED)
    user = User.objects.filter(username=username).first()
    payload = start_admin_session(request, admin, user=user)
    return _set_admin_cookie(json_ok(payload), request)


admin_logout = user_logout


@require_GET
def admin_me(request):
    admin = get_admin_context(request)
    if not admin:
        return json_ok({"loggedIn": False})
    upload_count = 0 if admin["is_super"] else AdminUploadEvent.objects.filter(admin_username=admin["username"]).count()
    return json_ok({
        "loggedIn": True,
        "username": admin["username"],
        "isSuper": admin["is_super"],
        "adminLevel": admin["admin_level"],
        "uploadProjectCount": upload_count,
        "autoPromoteTarget": settings.LV1_AUTO_PROMOTE_PROJECT_COUNT,
        "uploadSettings": get_upload_limit_settings(),
    })


@require_POST
def legacy_admin_register(request):
    return json_error(
        "legacy admin registration disabled; use unified registration at /api/user/register",
        status=HTTPStatus.GONE,
    )


@require_admin()
@require_GET
def tokens_get(request):
    rows = AdminRegisterToken.objects.order_by("-id")[:200]
    return json_ok({"items": [
        {
            "id": row.pk,
            "token": row.token[:8] + "..." if row.token else "",
            "full_token": row.token or "",
            "created_by": row.created_by,
            "created_at": row.created_at,
            "admin_level": int(row.admin_level or 1),
            "used": row.used_by_admin_id is not None,
        }
        for row in rows
    ]})


@require_admin(level=2)
@require_POST
def tokens_create(request):
    body, error = _body(request)
    if error:
        return error
    try:
        level = max(1, min(3, int(body.get("admin_level", 1))))
    except (TypeError, ValueError):
        level = 1
    token = secrets.token_hex(32)
    AdminRegisterToken.objects.create(
        token=token,
        created_by=request.kflow_admin["username"],
        created_at=now_iso(),
        admin_level=level,
    )
    return json_ok({"ok": True, "token": token, "admin_level": level})


@require_admin()
@require_GET
def users_get(request):
    subscription = UserSubscription.objects.filter(user_id=OuterRef("pk"))
    rows = User.objects.annotate(
        download_count=Count("downloads", distinct=True),
        request_count=Count("download_requests", distinct=True),
        subscribed=Exists(subscription),
    ).order_by("-created_at")
    return json_ok({"items": [
        {
            "id": row.pk,
            "username": row.username or "",
            "email": row.email or "",
            "created_at": row.created_at,
            "download_count": int(row.download_count or 0),
            "request_count": int(row.request_count or 0),
            "is_subscribed": bool(row.subscribed),
        }
        for row in rows
    ]})


def tokens(request):
    if request.method == "GET":
        return tokens_get(request)
    if request.method == "POST":
        return tokens_create(request)
    from django.http import HttpResponseNotAllowed
    return HttpResponseNotAllowed(["GET", "POST"])
