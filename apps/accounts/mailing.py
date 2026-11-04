"""系统邮件配置、投递日志与事件通知。

三条约定：

1. **配置优先级**：``system_settings`` 里的 ``mail_smtp_*``（后台可改）优先，
   没配则回落到 ``settings.EMAIL_*``（环境变量）。老部署不改一行配置也能继续用。
2. **密码**：用 Fernet 加密后入库，密钥由 ``SECRET_KEY`` 派生（与
   ``apps/store/crypto.py`` 同一套派生方式）。接口永远不回传明文，只回 ``passwordSet``。
3. **投递必留痕**：每次发送先写 ``email_deliveries``（status=pending），成功后改 sent，
   失败改 failed 并保留 error 原文。后台据此统计与重发。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import ssl
import threading
from dataclasses import dataclass
from datetime import timedelta
from datetime import timezone as dt_timezone

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import close_old_connections
from django.db.models import Count
from django.utils import timezone

from apps.catalog.models import SystemSetting

from . import mail_templates
from .models import AdminAccount, EmailDelivery

logger = logging.getLogger(__name__)

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

KEY_HOST = "mail_smtp_host"
KEY_PORT = "mail_smtp_port"
KEY_USERNAME = "mail_smtp_username"
KEY_PASSWORD = "mail_smtp_password_enc"
KEY_FROM = "mail_smtp_from"
KEY_USE_TLS = "mail_smtp_use_tls"
KEY_USE_SSL = "mail_smtp_use_ssl"
KEY_TIMEOUT = "mail_smtp_timeout"

EVENT_REGISTER = "user_registered"
KEY_EVENT_REGISTER = "mail_event_user_registered"

DEFAULT_EVENT = {"enabled": True, "recipients": [], "emails": []}

CATEGORY_LABELS = {"verification": "验证码", "event": "事件通知", "test": "测试邮件"}
EVENT_LABELS = {
    "verification_register": "注册验证码",
    "verification_login": "登录验证码",
    "verification_bind": "绑定邮箱验证码",
    "user_registered": "新用户注册通知",
    "manual_test": "后台测试邮件",
    "manual_retry": "后台手动重发",
}


class MailConfigError(Exception):
    """配置不合法，message 直接回给前端。"""


def now_iso() -> str:
    return timezone.now().isoformat()


def _get(key: str, default: str = "") -> str:
    row = SystemSetting.objects.filter(pk=key).first()
    if not row:
        return default
    return row.setting_value if row.setting_value is not None else default


def _set(key: str, value: str, actor: str) -> None:
    SystemSetting.objects.update_or_create(
        setting_key=key,
        defaults={"setting_value": value, "updated_at": now_iso(), "updated_by": actor or ""},
    )


def _fernet() -> Fernet:
    secret = str(settings.SECRET_KEY).encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError):
        logger.warning("SMTP 密码无法解密，SECRET_KEY 可能已更换")
        return ""


def _as_int(value, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _as_bool(value, fallback: bool) -> bool:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


@dataclass
class MailConfig:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    timeout: int = 10
    source: str = "none"

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_email)

    def public(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "fromEmail": self.from_email,
            "useTls": self.use_tls,
            "useSsl": self.use_ssl,
            "timeout": self.timeout,
            "source": self.source,
            "configured": self.configured,
            "passwordSet": bool(self.password),
        }


def load_config() -> MailConfig:
    host = _get(KEY_HOST).strip()
    if host:
        username = _get(KEY_USERNAME).strip()
        return MailConfig(
            host=host,
            port=_as_int(_get(KEY_PORT), 587),
            username=username,
            password=decrypt_secret(_get(KEY_PASSWORD)),
            from_email=_get(KEY_FROM).strip() or username or settings.DEFAULT_FROM_EMAIL,
            use_tls=_as_bool(_get(KEY_USE_TLS), True),
            use_ssl=_as_bool(_get(KEY_USE_SSL), False),
            timeout=max(1, _as_int(_get(KEY_TIMEOUT), 10)),
            source="database",
        )
    env_host = str(getattr(settings, "EMAIL_HOST", "") or "").strip()
    return MailConfig(
        host=env_host,
        port=_as_int(getattr(settings, "EMAIL_PORT", 587), 587),
        username=str(getattr(settings, "EMAIL_HOST_USER", "") or ""),
        password=str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""),
        from_email=str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""),
        use_tls=bool(getattr(settings, "EMAIL_USE_TLS", True)),
        use_ssl=bool(getattr(settings, "EMAIL_USE_SSL", False)),
        timeout=max(1, _as_int(getattr(settings, "EMAIL_TIMEOUT", 10), 10)),
        source="environment" if env_host else "none",
    )


def save_config(payload: dict, actor: str) -> MailConfig:
    """保存 SMTP 配置。password 字段缺省表示「保持原值」，传空串表示不改。"""
    host = str(payload.get("host") or "").strip()
    username = str(payload.get("username") or "").strip()
    from_email = str(payload.get("fromEmail") or payload.get("from_email") or "").strip()
    use_tls = bool(payload.get("useTls", True))
    use_ssl = bool(payload.get("useSsl", False))
    timeout = _as_int(payload.get("timeout"), 10)
    port = _as_int(payload.get("port"), 587)

    if host and (" " in host or "/" in host):
        raise MailConfigError("SMTP 主机只填域名或 IP，不要带协议和路径")
    if not 1 <= port <= 65535:
        raise MailConfigError("端口需在 1-65535 之间")
    if use_tls and use_ssl:
        raise MailConfigError("STARTTLS 与 SSL 只能二选一：465 用 SSL，587 用 STARTTLS")
    if not 1 <= timeout <= 60:
        raise MailConfigError("超时时间需在 1-60 秒之间")
    if from_email and "@" not in from_email:
        raise MailConfigError("发件人地址格式不正确")

    _set(KEY_HOST, host, actor)
    _set(KEY_PORT, str(port), actor)
    _set(KEY_USERNAME, username, actor)
    _set(KEY_FROM, from_email, actor)
    _set(KEY_USE_TLS, "1" if use_tls else "0", actor)
    _set(KEY_USE_SSL, "1" if use_ssl else "0", actor)
    _set(KEY_TIMEOUT, str(timeout), actor)

    password = payload.get("password")
    if isinstance(password, str) and password:
        _set(KEY_PASSWORD, encrypt_secret(password), actor)
    elif password == "" and payload.get("clearPassword"):
        _set(KEY_PASSWORD, "", actor)

    return load_config()


def _blank_event() -> dict:
    return {"enabled": True, "recipients": [], "emails": [], "selectAll": False}


def event_settings() -> dict:
    """读取事件通知配置。

    新结构：``{"enabled", "recipients": [管理员用户名], "emails": [额外邮箱]}``。
    旧结构里的 ``"admins": true``（发给全体）仍然兼容：读出来标成 ``selectAll``，
    由 :func:`resolve_recipients` 展开，避免升级后线上已配的开关直接失效。
    """
    raw = _get(KEY_EVENT_REGISTER, "")
    if not raw:
        return _blank_event()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return _blank_event()
    if not isinstance(data, dict):
        return _blank_event()
    emails = [str(item).strip().lower() for item in data.get("emails") or [] if str(item).strip()]
    recipients = [str(item).strip() for item in data.get("recipients") or [] if str(item).strip()]
    select_all = bool(data.get("admins", False)) and "recipients" not in data
    return {
        "enabled": bool(data.get("enabled", True)),
        "recipients": recipients,
        "emails": emails,
        "selectAll": select_all,
    }


def save_event_settings(payload: dict, actor: str) -> dict:
    """保存收件人名单。没绑邮箱的管理员会被静默剔除，不允许进篮子。"""
    emails: list[str] = []
    for item in payload.get("emails") or []:
        address = str(item).strip().lower()
        if not address:
            continue
        if "@" not in address or " " in address:
            raise MailConfigError(f"邮箱格式不正确：{address}")
        if address not in emails:
            emails.append(address)

    recipients: list[str] = []
    if isinstance(payload.get("recipients"), list):
        for item in payload["recipients"]:
            name = str(item).strip()
            if not name or name in recipients:
                continue
            admin = AdminAccount.objects.filter(username=name).first()
            if not admin or not (admin.email or "").strip():
                continue
            recipients.append(name)

    data = {
        "enabled": bool(payload.get("enabled", True)),
        "recipients": recipients,
        "emails": emails,
    }
    _set(KEY_EVENT_REGISTER, json.dumps(data, ensure_ascii=False), actor)
    return event_settings()


def admin_directory() -> list[dict]:
    """全部管理员，含没绑邮箱的 —— 后台拖拽池要把这些显示成灰色不可拖。"""
    rows = (
        AdminAccount.objects.order_by("admin_level", "username")
        .values("username", "email", "admin_level", "is_super")
    )
    return [
        {
            "username": row["username"],
            "email": (row["email"] or "").strip(),
            "hasEmail": bool((row["email"] or "").strip()),
            "adminLevel": int(row["admin_level"] or 1),
            "isSuper": bool(row["is_super"]),
        }
        for row in rows
    ]


def admin_recipients() -> list[dict]:
    return [item for item in admin_directory() if item["hasEmail"]]


def resolve_recipients(config: dict | None = None) -> list[str]:
    config = config or event_settings()
    directory = admin_directory()
    if config.get("selectAll"):
        pool = [item for item in directory if item["hasEmail"]]
    else:
        wanted = {str(name).strip() for name in config.get("recipients") or []}
        pool = [item for item in directory if item["username"] in wanted and item["hasEmail"]]
    collected = [item["email"].lower() for item in pool]
    collected.extend(str(item).strip().lower() for item in config.get("emails") or [])
    seen: list[str] = []
    for address in collected:
        if address and address not in seen:
            seen.append(address)
    return seen


def _build_connection(config: MailConfig):
    """测试环境（非 SMTP backend）直接用默认连接，方便走 locmem 断言。"""
    if settings.EMAIL_BACKEND != SMTP_BACKEND:
        return get_connection()
    if not config.host:
        raise MailConfigError("邮件服务未配置：请填写 SMTP 主机，或设置 SMTP_HOST 环境变量")
    _ensure_ca_bundle()
    return get_connection(
        backend=SMTP_BACKEND,
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        use_tls=bool(config.use_tls and not config.use_ssl),
        use_ssl=bool(config.use_ssl),
        timeout=config.timeout,
        fail_silently=False,
    )


def _ensure_ca_bundle() -> None:
    """补上缺失的根证书路径。

    macOS + Homebrew Python 的 ``ssl.get_default_verify_paths()`` 常常返回
    ``cafile=None``（openssl 编译时没写死证书位置），于是 STARTTLS 直接报
    ``CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``。
    这里按常见位置回填 ``SSL_CERT_FILE``，只在默认路径不可用时动手。
    """
    if os.environ.get("SSL_CERT_FILE"):
        return
    paths = ssl.get_default_verify_paths()
    if paths.cafile and os.path.exists(paths.cafile):
        return
    for candidate in (
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ):
        if os.path.exists(candidate):
            os.environ["SSL_CERT_FILE"] = candidate
            logger.info("使用系统 CA 证书包：%s", candidate)
            return


def _short_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:500]


def friendly_error(text: str) -> str:
    """把 smtplib 的原始异常翻译成管理员能照着改配置的话。"""
    raw = (text or "").strip()
    lowered = raw.lower()
    if not raw:
        return "未知错误"
    if "nodename" in lowered or "name or service not known" in lowered or "getaddrinfo" in lowered:
        return f"无法解析 SMTP 主机地址，请检查主机名（原始错误：{raw}）"
    if "connection refused" in lowered:
        return f"SMTP 端口拒绝连接，请检查端口与 SSL / STARTTLS 是否匹配（原始错误：{raw}）"
    if "timed out" in lowered or "timeout" in lowered:
        return f"连接 SMTP 超时，请检查网络、端口或防火墙（原始错误：{raw}）"
    if "authentication" in lowered or "535" in lowered or "5.7.8" in lowered:
        return f"SMTP 认证失败，请检查账号与授权码（原始错误：{raw}）"
    if "starttls" in lowered:
        return f"服务器不支持 STARTTLS，请改用 SSL（465）或关闭加密（原始错误：{raw}）"
    if "certificate" in lowered or "ssl" in lowered:
        return f"TLS 握手失败，请确认加密方式与端口（原始错误：{raw}）"
    return raw


def site_base_url() -> str:
    return str(getattr(settings, "SITE_BASE_URL", "") or "http://127.0.0.1:9000").rstrip("/")


def send_mail_logged(
    *,
    to,
    subject: str,
    body: str,
    html_body: str = "",
    category: str = "system",
    event: str = "",
    related_user_id: int | None = None,
    created_by: str = "",
) -> EmailDelivery:
    recipients = [str(item).strip() for item in (to if isinstance(to, (list, tuple)) else [to]) if str(item).strip()]
    record = EmailDelivery.objects.create(
        category=category,
        event=event,
        to_email=", ".join(recipients),
        subject=subject[:200],
        status="pending",
        related_user_id=related_user_id,
        created_by=created_by,
        created_at=now_iso(),
    )
    if not recipients:
        record.status = "failed"
        record.error = "没有收件人"
        record.save(update_fields=["status", "error"])
        return record

    config = load_config()
    try:
        connection = _build_connection(config)
        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=config.from_email or settings.DEFAULT_FROM_EMAIL,
            to=recipients,
            connection=connection,
        )
        if html_body:
            message.attach_alternative(html_body, "text/html")
        sent = message.send(fail_silently=False)
        if not sent:
            raise RuntimeError("SMTP 未接受任何收件人")
    except Exception as exc:
        record.status = "failed"
        record.error = _short_error(exc)
        record.save(update_fields=["status", "error"])
        return record

    record.status = "sent"
    record.sent_at = now_iso()
    record.save(update_fields=["status", "sent_at"])
    return record


def _run_async(func, **kwargs) -> None:
    def runner():
        close_old_connections()
        try:
            func(**kwargs)
        except Exception:
            logger.exception("异步邮件发送失败 event=%s", kwargs.get("event"))
        finally:
            close_old_connections()

    threading.Thread(target=runner, daemon=True, name="kflow-mail").start()


def notify_user_registered(user, request_ip: str = "") -> list[str]:
    """新用户注册后通知管理员。未开启、没人绑定邮箱时静默返回。"""
    config = event_settings()
    if not config["enabled"]:
        return []
    recipients = resolve_recipients(config)
    if not recipients:
        return []

    created_at = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "KFlow 有新用户完成注册。",
        "",
        f"用户名：{user.username}",
        f"邮箱：{user.email}",
        f"注册时间：{created_at}",
    ]
    if request_ip:
        lines.append(f"来源 IP：{request_ip}")
    lines.extend(["", "—— 本邮件由 KFlow 系统邮件设置自动发送，可在 后台 → 系统设置 → 系统邮箱设置 中关闭。"])
    _run_async(
        send_mail_logged,
        to=recipients,
        subject=f"KFlow 新用户注册：{user.username}",
        body="\n".join(lines),
        html_body=mail_templates.render_user_registered(
            username=user.username,
            email=user.email,
            created_at=created_at,
            request_ip=request_ip,
            base_url=site_base_url(),
        ),
        category="event",
        event=EVENT_REGISTER,
        related_user_id=user.pk,
        created_by="system",
    )
    return recipients


def _local_day_start(days_ago: int = 0) -> str:
    now = timezone.localtime()
    start = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(dt_timezone.utc).isoformat(timespec="microseconds")


def delivery_stats() -> dict:
    today_start = _local_day_start(0)
    week_start = _local_day_start(6)
    total = EmailDelivery.objects.count()
    today = EmailDelivery.objects.filter(created_at__gte=today_start).count()
    last7 = EmailDelivery.objects.filter(created_at__gte=week_start).count()
    failed = EmailDelivery.objects.filter(status="failed").count()
    pending = EmailDelivery.objects.filter(status="pending").count()

    by_category = [
        {"category": row["category"], "label": CATEGORY_LABELS.get(row["category"], row["category"]), "count": row["total"]}
        for row in EmailDelivery.objects.values("category").annotate(total=Count("id")).order_by("-total")
    ]
    by_event = [
        {"event": row["event"], "label": EVENT_LABELS.get(row["event"], row["event"] or "未分类"), "count": row["total"]}
        for row in EmailDelivery.objects.exclude(event="")
        .values("event")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    ]

    daily = []
    for offset in range(6, -1, -1):
        start = _local_day_start(offset)
        end = _local_day_start(offset - 1) if offset > 0 else None
        query = EmailDelivery.objects.filter(created_at__gte=start)
        if end:
            query = query.filter(created_at__lt=end)
        day = (timezone.localtime() - timedelta(days=offset)).strftime("%m-%d")
        daily.append({"date": day, "count": query.count()})

    sent = EmailDelivery.objects.filter(status="sent").count()
    return {
        "total": total,
        "today": today,
        "last7": last7,
        "failed": failed,
        "pending": pending,
        "sent": sent,
        "successRate": round(sent * 100 / total, 1) if total else None,
        "byCategory": by_category,
        "byEvent": by_event,
        "daily": daily,
    }


def recent_deliveries(*, limit: int = 20, offset: int = 0, status: str = "", event: str = "") -> dict:
    query = EmailDelivery.objects.all()
    if status:
        query = query.filter(status=status)
    if event:
        query = query.filter(event=event)
    total = query.count()
    rows = query.order_by("-id")[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": row.id,
                "category": row.category,
                "categoryLabel": CATEGORY_LABELS.get(row.category, row.category),
                "event": row.event,
                "eventLabel": EVENT_LABELS.get(row.event, row.event or "未分类"),
                "toEmail": row.to_email,
                "subject": row.subject,
                "status": row.status,
                "error": row.error,
                "createdAt": row.created_at,
                "sentAt": row.sent_at,
            }
            for row in rows
        ],
    }


def resend_delivery(delivery_id: int, actor: str) -> EmailDelivery:
    record = EmailDelivery.objects.filter(pk=delivery_id).first()
    if not record:
        raise MailConfigError("记录不存在")
    recipients = [item.strip() for item in (record.to_email or "").split(",") if item.strip()]
    if not recipients:
        raise MailConfigError("该记录没有收件人")
    body = f"这是 KFlow 后台重新投递的邮件（原记录 #{record.id}）。\n\n原主题：{record.subject}\n"
    return send_mail_logged(
        to=recipients,
        subject=f"[重发] {record.subject}" if record.subject else "KFlow 重发邮件",
        body=body,
        category="test",
        event="manual_retry",
        related_user_id=record.related_user_id,
        created_by=actor,
    )
