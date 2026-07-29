"""SMTP delivery and persistent, purpose-scoped email verification codes."""
from __future__ import annotations

import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app import config
from app.db import begin_immediate_with_retry, get_db
from app.utils.crypto import hash_password, verify_password
from app.utils.helpers import now_iso

PURPOSES = {"register", "login", "bind"}
_PURPOSE_LABELS = {
    "register": "注册 KFlow 账号",
    "login": "登录 KFlow",
    "bind": "绑定 KFlow 邮箱",
}


class EmailCodeError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def mask_email(value: str) -> str:
    email = normalize_email(value)
    if "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        shown = local[:1] + "*"
    else:
        shown = local[:2] + "*" * min(6, len(local) - 2)
    return f"{shown}@{domain}"


def smtp_is_configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_FROM)


def _send_mail(email: str, code: str, purpose: str) -> None:
    if not smtp_is_configured():
        raise EmailCodeError("email service unavailable", 503)

    label = _PURPOSE_LABELS[purpose]
    message = EmailMessage()
    message["Subject"] = f"KFlow 验证码：{code}"
    message["From"] = config.SMTP_FROM
    message["To"] = email
    message.set_content(
        f"你正在{label}。\n\n验证码：{code}\n\n验证码 10 分钟内有效，请勿转发给他人。"
    )

    smtp_cls = smtplib.SMTP_SSL if config.SMTP_USE_SSL else smtplib.SMTP
    with smtp_cls(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_SECONDS) as client:
        if not config.SMTP_USE_SSL and config.SMTP_USE_TLS:
            client.starttls()
        if config.SMTP_USERNAME:
            client.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        client.send_message(message)


_EMAIL_IP_LIMIT_PER_HOUR = 20


def _check_ip_hourly_limit(conn, ip: str) -> None:
    """Raise EmailCodeError if ip has hit the per-hour cap."""
    if not ip:
        return
    now = datetime.now(timezone.utc)
    hour_ago = (now - timedelta(hours=1)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM email_verification_codes "
        "WHERE request_ip = ? AND created_at >= ?",
        (ip, hour_ago),
    ).fetchone()
    if row and int(row["n"] or 0) >= _EMAIL_IP_LIMIT_PER_HOUR:
        raise EmailCodeError("verification code hourly limit reached for your IP", 429)


def issue_verification_code(email: str, purpose: str, request_ip: str = "") -> bool:
    """Create and deliver a code. Returns False only for a deliberately silent login miss."""
    email = normalize_email(email)
    if purpose not in PURPOSES:
        raise EmailCodeError("invalid verification purpose")
    if not config.EMAIL_RE.fullmatch(email):
        raise EmailCodeError("invalid email format")
    if not smtp_is_configured():
        raise EmailCodeError("email service unavailable", 503)

    conn = get_db()
    now = datetime.now(timezone.utc)
    hour_ago = (now - timedelta(hours=1)).isoformat()
    resend_after = (now - timedelta(seconds=config.EMAIL_CODE_RESEND_SECONDS)).isoformat()

    if purpose == "login":
        user = conn.execute(
            "SELECT id FROM users WHERE lower(email) = ? AND email_verified_at IS NOT NULL LIMIT 1",
            (email,),
        ).fetchone()
        if not user:
            return False
    elif purpose == "register":
        owner = conn.execute(
            "SELECT id FROM users WHERE lower(email) = ? AND email_verified_at IS NOT NULL LIMIT 1",
            (email,),
        ).fetchone()
        if owner:
            raise EmailCodeError("email already registered", 409)

    code = f"{secrets.randbelow(1_000_000):06d}"
    created_at = now.isoformat()
    expires_at = (now + timedelta(seconds=config.EMAIL_CODE_TTL_SECONDS)).isoformat()
    code_hash = hash_password(code)

    begin_immediate_with_retry(conn)
    try:
        _check_ip_hourly_limit(conn, request_ip)
        # Rate checks belong inside the write transaction so concurrent requests
        # cannot both pass the cooldown and create two active messages.
        recent = conn.execute(
            "SELECT created_at FROM email_verification_codes "
            "WHERE email = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
            (email, purpose),
        ).fetchone()
        if recent and recent["created_at"] > resend_after:
            raise EmailCodeError("verification code requested too frequently", 429)
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM email_verification_codes "
            "WHERE email = ? AND purpose = ? AND created_at >= ?",
            (email, purpose, hour_ago),
        ).fetchone()["n"]
        if int(count) >= config.EMAIL_CODE_MAX_SENDS_PER_HOUR:
            raise EmailCodeError("verification code hourly limit reached", 429)
        conn.execute(
            "UPDATE email_verification_codes SET used_at = ? "
            "WHERE email = ? AND purpose = ? AND used_at IS NULL",
            (created_at, email, purpose),
        )
        cursor = conn.execute(
            "INSERT INTO email_verification_codes "
            "(email, purpose, code_hash, request_ip, attempt_count, created_at, expires_at, used_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?, NULL)",
            (email, purpose, code_hash, request_ip or "", created_at, expires_at),
        )
        code_id = cursor.lastrowid
        conn.commit()
    except EmailCodeError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise

    try:
        _send_mail(email, code, purpose)
    except EmailCodeError:
        conn.execute("UPDATE email_verification_codes SET used_at = ? WHERE id = ?", (now_iso(), code_id))
        conn.commit()
        raise
    except Exception as exc:
        conn.execute("UPDATE email_verification_codes SET used_at = ? WHERE id = ?", (now_iso(), code_id))
        conn.commit()
        raise EmailCodeError("email delivery failed", 503) from exc
    return True


def consume_verification_code(conn, email: str, purpose: str, code: str) -> None:
    """Verify and consume the newest active code inside the caller's transaction."""
    email = normalize_email(email)
    raw_code = (code or "").strip()
    row = conn.execute(
        "SELECT * FROM email_verification_codes "
        "WHERE email = ? AND purpose = ? AND used_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (email, purpose),
    ).fetchone()
    if not row:
        raise EmailCodeError("invalid or expired verification code")
    if row["expires_at"] <= now_iso():
        conn.execute("UPDATE email_verification_codes SET used_at = ? WHERE id = ?", (now_iso(), row["id"]))
        raise EmailCodeError("invalid or expired verification code")
    if int(row["attempt_count"] or 0) >= config.EMAIL_CODE_MAX_ATTEMPTS:
        conn.execute("UPDATE email_verification_codes SET used_at = ? WHERE id = ?", (now_iso(), row["id"]))
        raise EmailCodeError("verification attempts exceeded")
    if not verify_password(raw_code, row["code_hash"]):
        attempts = int(row["attempt_count"] or 0) + 1
        conn.execute(
            "UPDATE email_verification_codes SET attempt_count = ?, used_at = CASE WHEN ? >= ? THEN ? ELSE used_at END "
            "WHERE id = ?",
            (attempts, attempts, config.EMAIL_CODE_MAX_ATTEMPTS, now_iso(), row["id"]),
        )
        raise EmailCodeError("invalid or expired verification code")
    conn.execute("UPDATE email_verification_codes SET used_at = ? WHERE id = ?", (now_iso(), row["id"]))
