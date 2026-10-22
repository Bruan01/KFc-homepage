"""Bind a one-use administrator code to the authenticated existing account."""
from django.conf import settings
from django.db import transaction
from django.db.models import Q

from .models import AdminAccount, AdminRegisterToken, User
from .services import AccountError, now_iso, verify_user_password


def claim_admin_code(invite, admin):
    claimed = AdminRegisterToken.objects.filter(pk=invite.pk, used_by_admin__isnull=True).filter(Q(used_at__isnull=True) | Q(used_at="")).update(
        used_by_admin=admin, used_at=now_iso())
    if not claimed:
        raise AccountError("激活码无效或已被使用", status=409)


def activate_existing_user(user_id, code, password):
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        admin = AdminAccount.objects.select_for_update().filter(username=user.username).first()
        if user.is_system_generated:
            raise AccountError("系统虚拟账号不能激活管理员权限", status=403)
        if user.username == settings.ADMIN_USERNAME or (admin and admin.is_super):
            raise AccountError("当前账号已是主管理员，无需使用激活码")
        if not user.email_verified_at and not admin:
            raise AccountError("请先完成账号的邮箱验证注册")
        if not user.has_usable_password():
            raise AccountError("当前账号未设置可用密码，请先设置登录密码")
        if not verify_user_password(user, password):
            raise AccountError("当前账号密码不正确", status=403)
        invite = AdminRegisterToken.objects.select_for_update().filter(token=code).first()
        if not invite or invite.admin_level not in {1, 2, 3}:
            raise AccountError("激活码无效或已被使用")
        # A lost response can safely be retried by the same account. Another
        # account cannot reuse the code, and a retry never lowers its level.
        if invite.used_by_admin_id is not None or bool(invite.used_at):
            if admin and invite.used_by_admin_id == admin.pk and invite.used_at and admin.admin_level >= invite.admin_level:
                return user, admin, True
            raise AccountError("激活码无效或已被使用")
        if admin and admin.admin_level >= invite.admin_level:
            raise AccountError(f"当前已是 lv{admin.admin_level} 管理员，请使用更高等级的激活码")
        if not admin:
            admin = AdminAccount.objects.create(username=user.username, password_hash=user.password, email=user.email,
                created_at=now_iso(), created_by=invite.created_by, is_super=0, admin_level=invite.admin_level)
        else:
            admin.admin_level = invite.admin_level
            admin.password_hash = user.password
            admin.email = user.email
            admin.save(update_fields=["admin_level", "password_hash", "email"])
        claim_admin_code(invite, admin)
        return user, admin, False
