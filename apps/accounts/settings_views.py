"""Private account settings; passwords are never returned to the client."""
import ipaddress
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from apps.core.http import client_ip, read_json, InvalidJSON
from apps.core.permissions import require_user
from apps.core.responses import json_ok, json_error
from .models import AdminAccount, LegacySession, User
from .services import verify_user_password, verify_admin_password, now_iso


def private(response):
    response["Cache-Control"] = "no-store"
    return response


@require_GET
@require_user
def account_settings(request):
    user, ip = request.user, client_ip(request)
    try:
        address = ipaddress.ip_address(ip)
        location = "本机访问" if address.is_loopback else "内网访问" if address.is_private else "暂未获取地理位置"
    except ValueError:
        location = "暂未获取"
    return private(json_ok({"username": user.username, "email": user.email,
                           "email_verified": bool(user.email_verified_at), "created_at": user.created_at,
                           "password_set": user.has_usable_password(), "password_changed_at": user.password_changed_at,
                           "ip": ip, "ip_location": location}))


@require_POST
@require_user
def change_password(request):
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("请求格式错误")
    old, new, confirm = (body.get(k, "") for k in ["current_password", "new_password", "confirm_password"])
    if not all(isinstance(v, str) for v in [old, new, confirm]):
        return json_error("请输入有效密码")
    if not 8 <= len(new) <= 128 or new != confirm:
        return json_error("新密码须为 8–128 位，且两次输入一致")
    key = f"password-change:{request.user.pk}"
    cache.add(key, 0, 300)
    if cache.incr(key) > 8:
        return json_error("尝试次数过多，请 5 分钟后再试", status=429)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        admin = AdminAccount.objects.filter(username=user.username).first()
        valid = verify_user_password(user, old) or bool(admin and verify_admin_password(admin, old))
        if not valid and user.username == settings.ADMIN_USERNAME and not user.password_changed_at:
            from django.utils.crypto import constant_time_compare
            valid = constant_time_compare(old, settings.ADMIN_PASSWORD)
        if not valid:
            return json_error("当前密码不正确", status=403)
        if old == new:
            return json_error("新密码不能与当前密码相同")
        user.set_password(new)
        user.password_changed_at = now_iso()
        user.save(update_fields=["password", "password_changed_at"])
        if admin:
            admin.password_hash = user.password
            admin.save(update_fields=["password_hash"])
        elif user.username == settings.ADMIN_USERNAME:
            AdminAccount.objects.create(username=user.username, password_hash=user.password, is_super=1,
                                        admin_level=3, email=user.email, created_at=now_iso(), created_by=user.username)
        current_key = request.session.session_key
        for session in Session.objects.filter(expire_date__gt=timezone.now()).exclude(session_key=current_key).iterator():
            data = session.get_decoded()
            if str(data.get("_auth_user_id")) == str(user.pk) or data.get("admin_username") == user.username:
                session.delete()
        LegacySession.objects.filter(username=user.username).delete()
    update_session_auth_hash(request, user)
    cache.delete(key)
    from .views import _set_admin_cookie
    response = private(json_ok({"changed": True, "message": "密码已更新，其他设备已退出登录"}))
    return _set_admin_cookie(response, request) if admin or user.username == settings.ADMIN_USERNAME else response
