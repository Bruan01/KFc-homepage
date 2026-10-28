import copy
from urllib.parse import quote

from django.db import transaction
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin
from apps.core.responses import json_error, json_ok
from .models import AssistantReplyJob, AssistantSettings, timestamp
from .provider import complete, encrypt_key, normalize_url
from .services import counted_jobs, official_user, system_messages, worker_alive


LIMITS = [("daily_limit_per_user", 1000, "每位用户每天的次数"), ("min_interval_seconds", 3600, "最短提问间隔"), ("daily_limit_total", 100000, "每天的总次数")]


def parse_config(body, saved, *, for_test=False):
    config = copy.copy(saved)
    for field, limit in [("base_url", 500), ("model", 150), ("persona", 4000), ("knowledge", 20000)]:
        value = body.get(field, getattr(saved, field))
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"{field} 格式无效或内容过长")
        setattr(config, field, value.strip())
    for field, maximum, label in LIMITS:
        value = body.get(field, getattr(saved, field))
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise ValueError(f"{label}需为 0–{maximum} 之间的整数")
        setattr(config, field, value)
    if config.base_url:
        config.base_url = normalize_url(config.base_url)
    enabled = body.get("enabled", saved.enabled)
    if not isinstance(enabled, bool):
        raise ValueError("启用状态无效")
    config.enabled = enabled
    key = body.get("api_key", "")
    clear = body.get("clear_api_key", False)
    if not isinstance(key, str) or len(key) > 8192 or "\r" in key or "\n" in key or not isinstance(clear, bool):
        raise ValueError("API Key 格式无效")
    if clear and key.strip():
        raise ValueError("请只选择清除旧密钥或填写新密钥其中一种操作")
    if key.strip():
        config.api_key_ciphertext = encrypt_key(key.strip())
    elif clear:
        config.api_key_ciphertext = ""
    if config.enabled or for_test:
        if not config.base_url or not config.model:
            raise ValueError("请先填写小 K 的 API 地址和模型名称")
        if config.enabled and not for_test and not official_user():
            raise ValueError("请先在上方设置小 K 官方账号，再启用 AI 助手")
    return config


def config_payload(config):
    official = official_user()
    return {
        "enabled": config.enabled, "base_url": config.base_url, "model": config.model,
        "persona": config.persona, "knowledge": config.knowledge, "has_api_key": bool(config.api_key_ciphertext),
        "daily_limit_per_user": config.daily_limit_per_user, "min_interval_seconds": config.min_interval_seconds,
        "daily_limit_total": config.daily_limit_total, "today_requests": counted_jobs().count(),
        "official_account": {"username": official.username, "display_name": official.display_name or official.username} if official else None,
        "worker_alive": worker_alive(config), "updated_at": config.updated_at, "updated_by": config.updated_by,
    }


@require_admin(super_only=True)
@require_http_methods(["GET", "POST"])
def assistant_settings(request):
    if request.method == "GET":
        return json_ok({"settings": config_payload(AssistantSettings.objects.filter(pk=1).first() or AssistantSettings())})
    try:
        body = read_json(request)
        with transaction.atomic():
            row, _ = AssistantSettings.objects.get_or_create(pk=1)
            row = AssistantSettings.objects.select_for_update().get(pk=1)
            config = parse_config(body, row)
            config.revision = row.revision + 1
            config.updated_at = timestamp(); config.updated_by = request.kflow_admin["username"]
            config.save(update_fields=["enabled", "base_url", "model", "persona", "knowledge", "api_key_ciphertext",
                                       "daily_limit_per_user", "min_interval_seconds", "daily_limit_total",
                                       "revision", "updated_at", "updated_by"])
    except (InvalidJSON, ValueError) as exc:
        return json_error("请求格式有误，请重试" if isinstance(exc, InvalidJSON) else str(exc))
    return json_ok({"settings": config_payload(config)})


@require_admin(super_only=True)
@require_POST
def test_reply(request):
    try:
        body = read_json(request)
        prompt = body.get("prompt", "你好，小 K，请简单介绍一下自己。")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1000:
            raise ValueError("测试消息请输入 1–1000 个字")
        config = parse_config(body, AssistantSettings.objects.filter(pk=1).first() or AssistantSettings(), for_test=True)
        answer = complete(config, system_messages(config) + [{"role": "user", "content": prompt.strip()}])
    except (InvalidJSON, ValueError) as exc:
        return json_error("请求格式有误，请重试" if isinstance(exc, InvalidJSON) else str(exc))
    except Exception:
        return json_error("测试未完成，请检查小 K 的 API 配置后重试", status=502)
    return json_ok({"reply": answer})


@require_admin(super_only=True)
@require_GET
def reply_records(request):
    rows = AssistantReplyJob.objects.select_related("result_comment", "result_message").order_by("-created_at", "-pk")[:20]
    items = []
    for row in rows:
        reply = ""
        if row.result_comment and not row.result_comment.is_deleted:
            reply = row.result_comment.content
        elif row.result_message:
            reply = row.result_message.content
        if row.post_id is None:
            link = f"/messages?user={quote(row.requester_username, safe='')}"
        else:
            link = f"/murmurs?post={row.post_id}" + (f"&comment={row.result_comment_id}#murmur-comment-{row.result_comment_id}" if row.result_comment_id else "")
        items.append({"id": str(row.pk), "status": row.status, "requester_username": row.requester_username,
                      "trigger_excerpt": row.trigger_excerpt, "reply": reply, "error": row.last_error,
                      "created_at": row.created_at, "link": link, "source": "dm" if row.post_id is None else "murmur"})
    return json_ok({"items": items})


@require_admin(super_only=True)
@require_POST
def retry_reply(request, job_id):
    config = AssistantSettings.objects.filter(pk=1, enabled=True).first()
    if not config:
        return json_error("请先启用小 K AI 助手")
    official = official_user()
    if not official:
        return json_error("请先设置官方账号")
    changed = AssistantReplyJob.objects.filter(pk=job_id, status="failed", result_comment__isnull=True, result_message__isnull=True, official=official).update(
        status="queued", attempts=0, claim_token="", next_attempt_at="", last_error="", updated_at=timestamp())
    if not changed:
        return json_error("该记录当前不能重试，请刷新记录", status=409)
    return json_ok({"queued": True})
