import copy
import hashlib
import json
from datetime import timedelta

from django.utils import timezone

from .provider import encrypt_key, normalize_url


CONNECTION_FIELDS = ("base_url", "model", "api_key_ciphertext", "timeout_seconds", "max_output_tokens", "token_parameter")


def connection_fingerprint(row):
    data = {key: getattr(row, key) for key in CONNECTION_FIELDS}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def remember_connection_check(row, status, error=""):
    from .models import PersonalitySettings, timestamp
    # An unsaved test or a slow result must not certify another saved connection.
    PersonalitySettings.objects.filter(pk=1, **{key: getattr(row, key) for key in CONNECTION_FIELDS}).update(
        provider_check={"status": status, "checked_at": timestamp(), "error": error[:300], "fingerprint": connection_fingerprint(row)})


def parse_config(body, saved):
    row = copy.copy(saved)
    for field in ("enabled", "ai_enabled", "evidence_enabled"):
        if field in body:
            if type(body[field]) is not bool:
                raise ValueError("启用状态无效")
            setattr(row, field, body[field])
    limits = [("recent_years", 3, 30), ("min_work_collects", 0, 10000000), ("min_character_collects", 0, 1000000),
              ("per_work_limit", 1, 10), ("daily_reports_per_user", 1, 50), ("timeout_seconds", 10, 180), ("max_output_tokens", 0, 32000)]
    for field, low, high in limits:
        if field in body:
            if type(body[field]) is not int or not low <= body[field] <= high:
                raise ValueError(f"{field} 应在 {low}–{high} 范围内")
            setattr(row, field, body[field])
    for field, limit in [("base_url", 500), ("model", 150)]:
        if field in body:
            if not isinstance(body[field], str) or len(body[field]) > limit:
                raise ValueError("接口配置格式无效")
            setattr(row, field, body[field].strip())
    if row.base_url:
        row.base_url = normalize_url(row.base_url)
    parameter = body.get("token_parameter", row.token_parameter)
    if parameter not in {"max_tokens", "max_completion_tokens", "none"}:
        raise ValueError("输出上限参数无效")
    row.token_parameter = parameter
    key, clear = body.get("api_key", ""), body.get("clear_api_key", False)
    if not isinstance(key, str) or len(key) > 8192 or any(c in key for c in ("\r", "\n")) or type(clear) is not bool:
        raise ValueError("密钥格式无效")
    if key.strip() and clear:
        raise ValueError("请只选择填写新密钥或清除旧密钥中的一种")
    if key.strip():
        row.api_key_ciphertext = encrypt_key(key.strip())
    elif clear:
        row.api_key_ciphertext = ""
    evidence_key, clear_evidence = body.get("evidence_api_key", ""), body.get("clear_evidence_api_key", False)
    if not isinstance(evidence_key, str) or len(evidence_key) > 8192 or any(c in evidence_key for c in ("\r", "\n")) or type(clear_evidence) is not bool:
        raise ValueError("搜索密钥格式无效")
    if evidence_key.strip() and clear_evidence:
        raise ValueError("请只选择填写新搜索密钥或清除旧搜索密钥中的一种")
    if evidence_key.strip():
        row.evidence_api_key_ciphertext = encrypt_key(evidence_key.strip())
    elif clear_evidence:
        row.evidence_api_key_ciphertext = ""
    if row.ai_enabled and not (row.base_url and row.model):
        raise ValueError("请填写文本服务地址与模型")
    return row


def worker_alive(row):
    try:
        return bool(row.worker_last_seen_at and timezone.datetime.fromisoformat(row.worker_last_seen_at) > timezone.now() - timedelta(seconds=180))
    except (ValueError, TypeError):
        return False


def public_config(row):
    from .evidence import evidence_connection
    fields = ["enabled", "ai_enabled", "base_url", "model", "timeout_seconds", "max_output_tokens", "token_parameter", "recent_years",
              "min_work_collects", "min_character_collects", "per_work_limit", "daily_reports_per_user"]
    check = row.provider_check
    fresh = isinstance(check, dict) and check.get("fingerprint") == connection_fingerprint(row)
    connection_check = {"status": check.get("status", "unchecked") if fresh else "unchecked",
                        "checked_at": check.get("checked_at", "") if fresh else "", "error": check.get("error", "") if fresh else ""}
    return {**{field: getattr(row, field) for field in fields}, "has_api_key": bool(row.api_key_ciphertext),
            "worker_alive": worker_alive(row), "updated_at": row.updated_at, "updated_by": row.updated_by,
            "saved": bool(row.updated_by), "connection_check": connection_check,
            "evidence_enabled": row.evidence_enabled, "has_evidence_api_key": bool(row.evidence_api_key_ciphertext),
            "evidence_available": evidence_connection(row) is not None}
