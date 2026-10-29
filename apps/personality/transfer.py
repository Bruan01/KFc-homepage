"""Portable character catalog only: never export users, answers or API secrets."""
from datetime import date
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import F

from .catalog import THEME_IDS, safe_image, validate_profile
from .models import Character, CharacterDiscovery, CharacterWorkScan, timestamp
from .policy import MAX_SOURCES

FORMAT = "xinying-catalog-1"
FIELDS = ["source_id", "name", "work_id", "work_name", "work_year", "image_url", "image_layout", "source_text", "extra_sources", "source_url", "source_stats", "status", "classic_candidate", "classic", "theme", "profile", "profile_check", "reviewed_by", "reviewed_at", "imported_at"]
FILTER_LIMITS = {"recent_years": (3, 30), "min_work_collects": (0, 10000000), "min_character_collects": (0, 1000000), "per_work_limit": (1, 10)}


def export_catalog():
    discovery = list(CharacterDiscovery.objects.order_by("source_id").values("source_id", "work_id", "name", "outcome", "reason", "first_seen_at", "last_attempt_at"))
    for row in discovery:
        if row["outcome"] == "fetching":
            row["outcome"] = "error"; row["reason"] = "导出时尚未完成，可手动重试"
    return {"format": FORMAT, "exported_at": timestamp(), "characters": list(Character.objects.order_by("source_id").values(*FIELDS)),
            "discovery": discovery, "work_scans": list(CharacterWorkScan.objects.values("work_id", "scope", "scanned_at"))}


def clean_record(data):
    if not isinstance(data, dict) or set(data) - set(FIELDS):
        raise ValueError("角色数据包含未知字段")
    for key in ["source_id", "work_id"]:
        if type(data.get(key)) is not int or not 0 < data[key] < 2147483647:
            raise ValueError("角色与作品 ID 需为正整数")
    for key, limit, required in [("name", 150, True), ("work_name", 250, True), ("source_text", 20000, False), ("image_url", 1000, False), ("source_url", 500, True), ("reviewed_by", 150, False), ("reviewed_at", 100, False), ("imported_at", 100, False)]:
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise ValueError(f"角色字段 {key} 格式无效")
    if data.get("image_url") and not safe_image(data["image_url"]):
        raise ValueError("角色图片需来自已支持的 Bangumi 图片域名")
    url = urlsplit(data["source_url"])
    if url.scheme != "https" or url.hostname not in {"bgm.tv", "bangumi.tv", "chii.in"} or url.username or url.password:
        raise ValueError("角色来源需为 Bangumi HTTPS 链接")
    year = data.get("work_year")
    if year is not None and (type(year) is not int or not 1900 <= year <= date.today().year):
        raise ValueError("作品年代无效")
    for field in ["classic", "classic_candidate"]:
        if type(data.get(field, False)) is not bool:
            raise ValueError("经典保留标记无效")
    if data.get("status", "candidate") not in {"candidate", "draft", "approved", "excluded"} or data.get("theme", "nature") not in THEME_IDS or data.get("image_layout", "portrait") not in {"portrait", "cutout"}:
        raise ValueError("角色状态、主题或图片布局无效")
    if not isinstance(data.get("source_stats", {}), dict) or not isinstance(data.get("profile", {}), dict) or not isinstance(data.get("profile_check", {}), dict):
        raise ValueError("角色统计或档案格式无效")
    sources = data.get("extra_sources", [])
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError("补充资料最多 12 项")
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"url", "text"} or not isinstance(source["url"], str) or not isinstance(source["text"], str):
            raise ValueError("补充资料格式无效")
        link = urlsplit(source["url"])
        if link.scheme != "https" or not link.hostname or link.username or link.password or len(source["url"]) > 1000 or not 10 <= len(source["text"]) <= 10000:
            raise ValueError("补充资料需要 HTTPS 来源和有效原文")
    row = Character(**data)
    check = row.profile_check
    if check:
        if not isinstance(check.get("status"), str) or check["status"] not in {"queued", "reviewing", "passed", "manual", "needs_sources", "error"} or not isinstance(check.get("issues", []), list) or any(not isinstance(item, str) or len(item) > 1500 for item in check.get("issues", [])) or len(check.get("issues", [])) > 20 or type(check.get("held", False)) is not bool or not isinstance(check.get("summary", ""), str):
            raise ValueError("档案复核记录格式无效")
        if check["status"] in {"queued", "reviewing"}:
            row.profile_check = {"status": "error", "issues": ["迁移时任务未完成，可重新生成或复核"]}
    if row.status == "approved":
        row.profile = validate_profile(row.profile, row)
    return {key: getattr(row, key) for key in FIELDS}


def import_catalog(payload, *, replace_reviewed=False):
    if not isinstance(payload, dict) or payload.get("format") != FORMAT or set(payload) - {"format", "exported_at", "characters", "discovery", "work_scans"}:
        raise ValueError("不是受支持的心映角色数据包")
    rows = payload.get("characters")
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError("每个数据包最多包含 5000 个角色")
    cleaned = [clean_record(row) for row in rows]
    if len({row["source_id"] for row in cleaned}) != len(cleaned):
        raise ValueError("数据包包含重复角色 ID")
    discoveries, scans = payload.get("discovery", []), payload.get("work_scans", [])
    if not isinstance(discoveries, list) or len(discoveries) > 50000 or not isinstance(scans, list) or len(scans) > 10000:
        raise ValueError("去重记录数量无效")
    if not cleaned and not discoveries and not scans:
        raise ValueError("数据包没有角色或去重记录")
    for row in discoveries:
        if not isinstance(row, dict) or set(row) != {"source_id", "work_id", "name", "outcome", "reason", "first_seen_at", "last_attempt_at"} or any(type(row.get(key)) is not int or row[key] <= 0 for key in ["source_id", "work_id"]):
            raise ValueError("角色去重记录格式无效")
        if row["outcome"] not in {"imported", "filtered", "error"} or any(not isinstance(row[key], str) or len(row[key]) > limit for key, limit in [("name", 150), ("reason", 300), ("first_seen_at", 100), ("last_attempt_at", 100)]):
            raise ValueError("角色去重记录内容无效")
    import re
    for row in scans:
        if not isinstance(row, dict) or set(row) != {"work_id", "scope", "scanned_at"} or type(row["work_id"]) is not int or row["work_id"] <= 0 or not isinstance(row["scope"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["scope"]) or not isinstance(row["scanned_at"], str) or len(row["scanned_at"]) > 100:
            raise ValueError("作品检查记录无效")
    counts = {"imported": 0, "preserved": 0}
    with transaction.atomic():
        # Acquire the SQLite write lock before reading conflict states.
        Character.objects.filter(source_id=cleaned[0]["source_id"] if cleaned else 0).update(imported_at=F("imported_at"))
        for data in cleaned:
            existing = Character.objects.filter(source_id=data["source_id"]).first()
            if existing and existing.status in {"approved", "excluded"} and not replace_reviewed:
                counts["preserved"] += 1
                continue
            defaults = {k: v for k, v in data.items() if k != "source_id"}
            if existing:
                defaults["revision"] = F("revision")+1
            Character.objects.update_or_create(source_id=data["source_id"], defaults=defaults)
            counts["imported"] += 1
        for row in discoveries:
            CharacterDiscovery.objects.get_or_create(source_id=row["source_id"], defaults={k: v for k, v in row.items() if k != "source_id"})
        for row in cleaned:
            CharacterDiscovery.objects.get_or_create(source_id=row["source_id"], defaults={"work_id": row["work_id"], "name": row["name"], "outcome": "imported", "reason": "由角色数据包导入"})
        for row in scans:
            CharacterWorkScan.objects.get_or_create(work_id=row["work_id"], scope=row["scope"], defaults={"scanned_at": row["scanned_at"]})
    return counts
