"""后台「系统邮箱设置」接口。

只给 lv3 及以上管理员。四件事：读写 SMTP 配置、发测试信、查投递记录、重发。
密码永不回传，只回 ``passwordSet``；留空表示沿用原密码。
"""
from __future__ import annotations

from http import HTTPStatus

from django.conf import settings
from django.http import HttpResponseNotAllowed
from django.utils import timezone

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin
from apps.core.responses import json_error, json_ok

from . import mail_templates, mailing
from .mailing import MailConfigError


def _payload(admin_username: str) -> dict:
    config = mailing.load_config()
    events = mailing.event_settings()
    directory = mailing.admin_directory()
    recent = mailing.recent_deliveries(limit=10)
    return {
        "config": config.public(),
        "events": {
            **events,
            "adminDirectory": directory,
            "adminCandidates": [item for item in directory if item["hasEmail"]],
            "resolvedRecipients": mailing.resolve_recipients(events),
            "eventKey": mailing.EVENT_REGISTER,
        },
        "stats": mailing.delivery_stats(),
        "deliveries": recent["items"],
        "deliveryTotal": recent["total"],
        "labels": {"category": mailing.CATEGORY_LABELS, "event": mailing.EVENT_LABELS},
        "operator": admin_username,
    }


@require_admin(3)
def mail_settings(request):
    if request.method == "GET":
        return json_ok(_payload(request.kflow_admin["username"]))
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("invalid json")

    actor = request.kflow_admin["username"]
    try:
        if isinstance(body.get("config"), dict):
            mailing.save_config(body["config"], actor)
        if isinstance(body.get("events"), dict):
            mailing.save_event_settings(body["events"], actor)
    except MailConfigError as exc:
        return json_error(str(exc))
    return json_ok(_payload(actor))


def _fallback_recipient(admin_username: str) -> str:
    """没有管理员绑邮箱时，仍然要能发测试信。

    优先级：当前管理员邮箱 → 事件收件人 → 发件人地址本身。
    最后一条很实用：SMTP 的发件人通常就是自己的邮箱，能收信。
    """
    from email.utils import parseaddr

    from django.conf import settings as dj_settings

    from .models import AdminAccount

    admin = AdminAccount.objects.filter(username=admin_username).exclude(email="").first()
    if admin and admin.email.strip():
        return admin.email.strip()
    resolved = mailing.resolve_recipients()
    if resolved:
        return resolved[0]
    for candidate in (
        mailing.load_config().from_email,
        getattr(dj_settings, "DEFAULT_FROM_EMAIL", ""),
    ):
        address = parseaddr(str(candidate or ""))[1]
        if "@" in address and "localhost" not in address:
            return address
    return ""


@require_admin(3)
def mail_test(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("invalid json")

    actor = request.kflow_admin["username"]
    target = str(body.get("to") or "").strip() or _fallback_recipient(actor)
    if not target:
        return json_error("没有可用的收件人：请先给管理员账号绑定邮箱，或在下方填写额外收件邮箱")
    if "@" not in target or " " in target:
        return json_error("收件邮箱格式不正确")

    created_at = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
    config = mailing.load_config()
    record = mailing.send_mail_logged(
        to=target,
        subject="KFlow 邮件配置测试",
        body="\n".join(
            [
                "这是一封测试邮件，说明当前 SMTP 配置可用。",
                "",
                f"发件人：{config.from_email}",
                f"触发人：{actor}",
                f"时间：{created_at}",
                "",
                "—— 来自 后台 → 系统设置 → 系统邮箱设置",
            ]
        ),
        html_body=mail_templates.render_test(
            from_email=config.from_email,
            actor=actor,
            created_at=created_at,
            base_url=mailing.site_base_url(),
        ),
        category="test",
        event="manual_test",
        created_by=actor,
    )
    if record.status != "sent":
        return json_error(
            f"发送失败：{mailing.friendly_error(record.error)}",
            status=HTTPStatus.BAD_GATEWAY,
            deliveryId=record.id,
        )
    return json_ok({"deliveryId": record.id, "to": target, "message": f"测试邮件已发送到 {target}"})


@require_admin(3)
def mail_deliveries(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        limit = max(1, min(100, int(request.GET.get("limit", "20"))))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = max(0, int(request.GET.get("offset", "0")))
    except (TypeError, ValueError):
        offset = 0
    status = str(request.GET.get("status") or "").strip()
    event = str(request.GET.get("event") or "").strip()
    if status not in {"", "pending", "sent", "failed"}:
        status = ""
    data = mailing.recent_deliveries(limit=limit, offset=offset, status=status, event=event)
    data["stats"] = mailing.delivery_stats()
    return json_ok(data)


@require_admin(3)
def mail_retry(request, delivery_id: int):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    actor = request.kflow_admin["username"]
    try:
        record = mailing.resend_delivery(delivery_id, actor)
    except MailConfigError as exc:
        return json_error(str(exc))
    if record.status != "sent":
        return json_error(
            f"重发失败：{mailing.friendly_error(record.error)}",
            status=HTTPStatus.BAD_GATEWAY,
            deliveryId=record.id,
        )
    return json_ok({"deliveryId": record.id, "message": "已重新投递"})


@require_admin(3)
def mail_capabilities(request):
    """给前端判断「环境变量是否已配好」，避免管理员误以为必须重填。"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    config = mailing.load_config()
    return json_ok(
        {
            "configured": config.configured,
            "source": config.source,
            "backend": settings.EMAIL_BACKEND,
            "canSend": config.configured or settings.EMAIL_BACKEND != mailing.SMTP_BACKEND,
        }
    )


@require_admin(3)
def mail_admin_email(request):
    """给管理员补绑接收通知的邮箱。

    只写 ``admin_accounts.email``（通知地址），不动 ``users.email``（登录凭据），
    所以不会影响这个人的登录方式。
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("invalid json")

    from django.db import IntegrityError

    from .models import AdminAccount

    username = str(body.get("username") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    if not username:
        return json_error("缺少管理员用户名")
    if "@" not in email or " " in email:
        return json_error("邮箱格式不正确")

    admin = AdminAccount.objects.filter(username=username).first()
    if not admin:
        return json_error("管理员不存在", status=HTTPStatus.NOT_FOUND)
    if AdminAccount.objects.filter(email__iexact=email).exclude(pk=admin.pk).exists():
        return json_error("这个邮箱已被其他管理员占用", status=HTTPStatus.CONFLICT)

    admin.email = email
    try:
        admin.save(update_fields=["email"])
    except IntegrityError:
        return json_error("这个邮箱已被其他管理员占用", status=HTTPStatus.CONFLICT)
    return json_ok({"ok": True, "username": username, "email": email})
