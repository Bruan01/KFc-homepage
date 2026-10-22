"""Django views for user and administrator authentication APIs."""
from __future__ import annotations

import secrets
from http import HTTPStatus

from django.conf import settings
from django.contrib.auth import logout, update_session_auth_hash
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.views.decorators.http import require_GET, require_POST

from apps.catalog.models import AdminUploadEvent
from apps.catalog.upload_limits import get_upload_limit_settings
from apps.core.http import InvalidJSON, client_ip, read_json
from apps.core.permissions import get_admin_context, require_admin, require_user
from apps.core.responses import json_error, json_ok
from apps.downloads.models import Download, DownloadRequest
from apps.points.services import award_registration
from .models import AdminAccount, AdminRegisterToken, User, UserSubscription
from .activation import activate_existing_user, claim_admin_code
from .onboarding import enroll_guide
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
    set_admin_session,
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
                ).filter(Q(used_at__isnull=True) | Q(used_at="")).first()
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
                claim_admin_code(invite, admin)
            award_registration(user)
            enroll_guide(user, visited=body.get("guide_visited") is True)
    except AccountError as exc:
        return json_error(exc.message, status=exc.status)
    except IntegrityError:
        return json_error("username or email already registered", status=HTTPStatus.CONFLICT)

    payload, is_admin = start_user_session(request, user)
    response = json_ok(payload)
    return _set_admin_cookie(response, request) if is_admin else response


@require_user
@require_POST
def activate_admin(request):
    body, error = _body(request)
    if error:
        return error
    code = body.get("activation_code", "")
    password = body.get("password", "")
    if not isinstance(code, str) or not code.strip() or len(code) > 256:
        return json_error("请输入有效的管理员激活码")
    if not isinstance(password, str) or not password or len(password) > 1024:
        return json_error("请填写当前登录账号的密码")
    try:
        user, admin, replayed = activate_existing_user(request.user.pk, code.strip(), password)
    except AccountError as exc:
        return json_error(exc.message, status=exc.status)
    except IntegrityError:
        return json_error("激活请求已处理，请刷新页面后重试", status=409)
    except OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return json_error("激活请求正在处理，请稍后重试", status=409)
        raise
    # Rotate the session on elevation and preserve auth if a legacy password
    # was upgraded during verification. No registration/daily reward is issued.
    update_session_auth_hash(request, user)
    set_admin_session(request, {"username": admin.username, "admin_level": admin.admin_level, "is_super": False})
    request.session.save()
    response = json_ok({"ok": True, "username": user.username, "role": "admin", "admin_level": admin.admin_level,
                        "adminLevel": admin.admin_level, "isSuper": False, "replayed": replayed})
    return _set_admin_cookie(response, request)


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
    # 令牌就是「一个可直接注册成 N 级管理员的凭据」，读到明文等于拿到那个身份。
    # 所以按查看者等级过滤：lv1 只能看到 lv1 令牌（那些他自己也能造），
    # 不能顺手把别人留下的 lv3 令牌复制走。
    viewer_level = int(request.kflow_admin["admin_level"])
    is_super = bool(request.kflow_admin["is_super"])
    queryset = AdminRegisterToken.objects.select_related("used_by_admin").order_by("-id")
    if not is_super:
        queryset = queryset.filter(admin_level__lte=viewer_level)
    rows = queryset[:200]
    return json_ok({"items": [
        {
            "id": row.pk,
            "token": row.token[:8] + "..." if row.token else "",
            "full_token": row.token or "",
            "created_by": row.created_by,
            "created_at": row.created_at,
            "admin_level": int(row.admin_level or 1),
            "used": row.used_by_admin_id is not None,
            "status": "used" if row.used_by_admin_id is not None else "unused",
            "used_by_username": row.used_by_admin.username if row.used_by_admin_id else "",
            "used_at": row.used_at or "",
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
        requested = max(1, min(3, int(body.get("level", body.get("admin_level", 1)))))
    except (TypeError, ValueError):
        requested = 1
    try:
        count = max(1, min(20, int(body.get("count", 1))))
    except (TypeError, ValueError):
        count = 1
    # 只能发「不高于自己」的等级。否则 lv2 可以发一张 lv3 邀请码给自己注册，
    # 整条提权链（上传 1 个项目 → 自动升 lv2 → 发 lv3 码 → 注册 lv3）就通了。
    ceiling = 3 if request.kflow_admin["is_super"] else int(request.kflow_admin["admin_level"])
    level = min(requested, ceiling)
    rows = [
        AdminRegisterToken(
            token=secrets.token_hex(32),
            created_by=request.kflow_admin["username"],
            created_at=now_iso(),
            admin_level=level,
        )
        for _ in range(count)
    ]
    with transaction.atomic():
        AdminRegisterToken.objects.bulk_create(rows)
    tokens = [row.token for row in rows]
    return json_ok({
        "ok": True,
        "tokens": tokens,
        "count": len(tokens),
        "adminLevel": level,
        "token": tokens[0],
        "admin_level": level,
    })


@require_admin()
@require_GET
def users_get(request):
    from .official import official_account_id
    official_id = official_account_id()
    subscription = UserSubscription.objects.filter(user_id=OuterRef("pk"))
    admin_rows = AdminAccount.objects.filter(username=OuterRef("username"))
    rows = User.objects.annotate(
        download_count=Count("downloads", distinct=True),
        request_count=Count("download_requests", distinct=True),
        subscribed=Exists(subscription),
        permission_level=Coalesce(Subquery(admin_rows.values("admin_level")[:1]), 0),
        permission_super=Coalesce(Subquery(admin_rows.values("is_super")[:1]), 0),
    ).order_by("-created_at")
    return json_ok({"items": [
        {
            "id": row.pk,
            "username": row.username or "",
            "display_name": row.display_name or row.username,
            "is_official": row.pk == official_id,
            "is_system_generated": row.is_system_generated,
            "admin_level": int(row.permission_level),
            "is_super": bool(row.permission_super or row.username == settings.ADMIN_USERNAME),
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
