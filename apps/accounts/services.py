"""Authentication, verification-code and session services for Django."""
from __future__ import annotations

import re
import secrets
from datetime import timedelta
from http import HTTPStatus

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.points.services import award_daily_activity
from .models import AdminAccount, EmailVerificationCode, User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PURPOSES = {"register", "login", "bind"}
PURPOSE_LABELS = {
    "register": "注册 KFlow 账号",
    "login": "登录 KFlow",
    "bind": "绑定 KFlow 邮箱",
}


class AccountError(Exception):
    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = int(status)


def now_iso():
    return timezone.now().isoformat()


def normalize_email(value):
    return str(value or "").strip().lower()


def mask_email(value):
    email = normalize_email(value)
    if "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    shown = local[:1] + "*" if len(local) <= 2 else local[:2] + "*" * min(6, len(local) - 2)
    return f"{shown}@{domain}"


def email_payload(user):
    verified = bool(user and user.email and user.email_verified_at)
    return {"emailMasked": mask_email(user.email) if verified else "", "hasVerifiedEmail": verified}


def _email_backend_available():
    backend = settings.EMAIL_BACKEND
    if backend == "django.core.mail.backends.smtp.EmailBackend":
        return bool(settings.EMAIL_HOST and settings.DEFAULT_FROM_EMAIL)
    return True


def _send_code(email, code, purpose):
    if not _email_backend_available():
        raise AccountError("email service unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
    message = EmailMessage(
        subject=f"KFlow 验证码：{code}",
        body=f"你正在{PURPOSE_LABELS[purpose]}。\n\n验证码：{code}\n\n验证码 10 分钟内有效，请勿转发给他人。",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
        connection=get_connection(),
    )
    try:
        sent = message.send(fail_silently=False)
    except Exception as exc:
        raise AccountError("email delivery failed", HTTPStatus.SERVICE_UNAVAILABLE) from exc
    if sent != 1:
        raise AccountError("email delivery failed", HTTPStatus.SERVICE_UNAVAILABLE)


def issue_verification_code(email, purpose, request_ip=""):
    email = normalize_email(email)
    purpose = str(purpose or "").strip().lower()
    if purpose not in PURPOSES:
        raise AccountError("invalid verification purpose")
    if not EMAIL_RE.fullmatch(email):
        raise AccountError("invalid email format")
    if not _email_backend_available():
        raise AccountError("email service unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
    if purpose == "login" and not User.objects.filter(email__iexact=email, email_verified_at__isnull=False).exists():
        return False
    if purpose == "register" and User.objects.filter(email__iexact=email, email_verified_at__isnull=False).exists():
        raise AccountError("email already registered", HTTPStatus.CONFLICT)

    now = timezone.now()
    created_at = now.isoformat()
    hour_ago = (now - timedelta(hours=1)).isoformat()
    resend_after = (now - timedelta(seconds=settings.EMAIL_CODE_RESEND_SECONDS)).isoformat()
    code = f"{secrets.randbelow(1_000_000):06d}"

    with transaction.atomic():
        if request_ip and EmailVerificationCode.objects.filter(request_ip=request_ip, created_at__gte=hour_ago).count() >= settings.EMAIL_CODE_IP_LIMIT_PER_HOUR:
            raise AccountError("verification code hourly limit reached for your IP", HTTPStatus.TOO_MANY_REQUESTS)
        recent = EmailVerificationCode.objects.filter(email=email, purpose=purpose).order_by("-id").first()
        if recent and recent.created_at > resend_after:
            raise AccountError("verification code requested too frequently", HTTPStatus.TOO_MANY_REQUESTS)
        if EmailVerificationCode.objects.filter(email=email, purpose=purpose, created_at__gte=hour_ago).count() >= settings.EMAIL_CODE_MAX_SENDS_PER_HOUR:
            raise AccountError("verification code hourly limit reached", HTTPStatus.TOO_MANY_REQUESTS)
        EmailVerificationCode.objects.filter(email=email, purpose=purpose, used_at__isnull=True).update(used_at=created_at)
        record = EmailVerificationCode.objects.create(
            email=email,
            purpose=purpose,
            code_hash=make_password(code),
            request_ip=request_ip or "",
            attempt_count=0,
            created_at=created_at,
            expires_at=(now + timedelta(seconds=settings.EMAIL_CODE_TTL_SECONDS)).isoformat(),
        )

    try:
        _send_code(email, code, purpose)
    except AccountError:
        EmailVerificationCode.objects.filter(pk=record.pk).update(used_at=now_iso())
        raise
    return True


def consume_verification_code(email, purpose, code):
    """Consume a code and return an error string, or an empty string on success.

    Call this inside ``transaction.atomic``. Returning the response from inside
    that block commits failed-attempt counters just like the legacy service.
    """
    email = normalize_email(email)
    raw_code = str(code or "").strip()
    row = EmailVerificationCode.objects.select_for_update().filter(
        email=email,
        purpose=purpose,
        used_at__isnull=True,
    ).order_by("-id").first()
    current = now_iso()
    if not row:
        return "invalid or expired verification code"
    if row.expires_at <= current:
        row.used_at = current
        row.save(update_fields=["used_at"])
        return "invalid or expired verification code"
    if int(row.attempt_count or 0) >= settings.EMAIL_CODE_MAX_ATTEMPTS:
        row.used_at = current
        row.save(update_fields=["used_at"])
        return "verification attempts exceeded"
    if not check_password(raw_code, row.code_hash):
        row.attempt_count = int(row.attempt_count or 0) + 1
        if row.attempt_count >= settings.EMAIL_CODE_MAX_ATTEMPTS:
            row.used_at = current
        row.save(update_fields=["attempt_count", "used_at"])
        return "invalid or expired verification code"
    row.used_at = current
    row.save(update_fields=["used_at"])
    return ""


def verify_user_password(user, raw_password):
    if user.check_password(raw_password):
        return True
    if constant_time_compare(str(raw_password), user.password or ""):
        user.set_password(raw_password)
        user.save(update_fields=["password"])
        return True
    return False


def verify_admin_password(admin, raw_password):
    updated = []

    def setter(password):
        updated.append(make_password(password))

    valid = check_password(raw_password, admin.password_hash, setter=setter)
    if not valid and constant_time_compare(str(raw_password), admin.password_hash or ""):
        updated.append(make_password(raw_password))
        valid = True
    if valid and updated:
        admin.password_hash = updated[-1]
        admin.save(update_fields=["password_hash"])
    return valid


def admin_for_username(username):
    if username == settings.ADMIN_USERNAME:
        return {"username": username, "is_super": True, "admin_level": 3}
    row = AdminAccount.objects.filter(username=username).first()
    if not row:
        return None
    return {"username": row.username, "is_super": bool(row.is_super), "admin_level": int(row.admin_level or 1)}


def set_admin_session(request, admin):
    request.session["admin_username"] = admin["username"]
    request.session["admin_is_super"] = bool(admin["is_super"])
    request.session["admin_level"] = int(admin["admin_level"])


def start_user_session(request, user):
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    admin = admin_for_username(user.username)
    if admin:
        set_admin_session(request, admin)
    request.session.save()
    with transaction.atomic():
        award_daily_activity(user)
    payload = {"ok": True, "token": request.session.session_key, "username": user.username, "user_id": user.pk}
    if admin:
        payload.update({"is_admin": True, "is_super": admin["is_super"], "admin_level": admin["admin_level"]})
    return payload, bool(admin)


def start_admin_session(request, admin, user=None):
    if user:
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    else:
        request.session.flush()
    set_admin_session(request, admin)
    request.session.save()
    payload = {
        "token": request.session.session_key,
        "username": admin["username"],
        "is_super": bool(admin["is_super"]),
        "admin_level": int(admin["admin_level"]),
    }
    if user:
        payload["user_id"] = user.pk
    return payload
