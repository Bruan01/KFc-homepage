"""Super-admin controls for the existing official community identity."""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin
from apps.core.responses import json_error, json_ok
from .models import OfficialCommunitySettings, User
from .official import MAX_TARGET_FOLLOWERS, adjust_managed_followers, initialize_existing_users, settings_payload


@require_admin(super_only=True)
@require_http_methods(["GET", "POST"])
def official_community(request):
    if request.method == "GET":
        config = OfficialCommunitySettings.objects.select_related("account").filter(pk=1).first()
        query = request.GET.get("q", "").strip()[:150]
        candidates = User.objects.filter(is_system_generated=False)
        if query:
            candidates = candidates.filter(Q(username__icontains=query) | Q(display_name__icontains=query))
        return json_ok({"settings": settings_payload(config), "candidates": [
            {"username": user.username, "display_name": user.display_name or user.username}
            for user in candidates.order_by("username")[:20]
        ]})
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("请求格式有误，请重试")
    username = body.get("account_username")
    target = body.get("target_follower_count")
    if not isinstance(username, str) or not username.strip() or len(username) > 150:
        return json_error("请填写已有官方账号的用户名")
    if type(target) is not int or not 0 <= target <= MAX_TARGET_FOLLOWERS:
        return json_error(f"目标粉丝数请输入 0–{MAX_TARGET_FOLLOWERS} 的整数")
    account = User.objects.filter(username=username.strip(), is_system_generated=False).first()
    if not account:
        return json_error("账号不存在或属于系统虚拟账号，请选择已有官方账号", status=404)
    with transaction.atomic():
        config, _ = OfficialCommunitySettings.objects.get_or_create(pk=1)
        config = OfficialCommunitySettings.objects.select_for_update().get(pk=1)
        config.account = account
        config.target_follower_count = target
        config.updated_by = request.kflow_admin["username"]
        config.updated_at = timezone.now().isoformat()
        config.save()
        initialized = initialize_existing_users(account)
        changes = adjust_managed_followers(account, target)
    return json_ok({"settings": settings_payload(config), "changes": {"initialized_follows": initialized, **changes}})
