"""展示热度曲线：读取时计算「展示值」，不向数据库写任何假数据。

真实浏览/点赞永远独立存在；展示值 = max(真实值, 曲线值)，乱序刷新也不会跳变。
碎碎念（murmurs）与论坛（forum）共用同一套公式，各自用 SystemSetting 前缀区分。

曲线的规则是「只涨不落」：帖子按成长天数从真实值涨到目标值，之后一直保持；
只有管理员关掉总开关或停用单帖设置时，数字才会回落。
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime

from django.utils import timezone

from apps.catalog.models import SystemSetting

MIN_TARGET_VIEWS = 120
MAX_TARGET_VIEWS = 5000
MAX_GROW_DAYS = 30

# 全局默认值；真值以 SystemSetting 中的 {prefix}.heat.* 为准。
DEFAULTS = {
    "enabled": False,
    "default_views": 300,
    "default_grow_days": 7,
    "default_like_ratio": 0.04,
    "quiet_minutes": 10,
    "max_views": 5000,
    "max_like_ratio": 0.08,
    # 关掉总开关时记录冻结时间：有值时按当时的展示值保持，不再变化。
    "frozen_at": "",
}

RATIO_BOUNDS = (0.01, 0.08)


def setting_key(prefix: str, name: str) -> str:
    return f"{prefix}.heat.{name}"


def get_config(prefix: str) -> dict:
    keys = {name: setting_key(prefix, name) for name in DEFAULTS}
    stored = dict(
        SystemSetting.objects.filter(setting_key__in=keys.values()).values_list("setting_key", "setting_value")
    )
    config = dict(DEFAULTS)
    for name, key in keys.items():
        raw = stored.get(key)
        if raw is None:
            continue
        try:
            if name == "enabled":
                config[name] = raw.strip() == "1"
            elif name == "frozen_at":
                config[name] = raw.strip()
            elif name in ("default_like_ratio", "max_like_ratio"):
                config[name] = float(raw)
            else:
                config[name] = int(raw)
        except (TypeError, ValueError):
            continue
    return _clamp_config(config)


def _clamp_config(config: dict) -> dict:
    config["default_views"] = max(MIN_TARGET_VIEWS, min(int(config["default_views"]), MAX_TARGET_VIEWS))
    config["default_grow_days"] = max(1, min(int(config["default_grow_days"]), MAX_GROW_DAYS))
    config["default_like_ratio"] = max(RATIO_BOUNDS[0], min(float(config["default_like_ratio"]), RATIO_BOUNDS[1]))
    config["max_like_ratio"] = max(RATIO_BOUNDS[0], min(float(config["max_like_ratio"]), RATIO_BOUNDS[1]))
    config["max_views"] = max(MIN_TARGET_VIEWS, min(int(config["max_views"]), 20000))
    config["quiet_minutes"] = max(0, min(int(config["quiet_minutes"]), 1440))
    return config


def save_config(prefix: str, values: dict, updated_by: str) -> dict:
    now = timezone.now().isoformat()
    for name in DEFAULTS:
        if name not in values:
            continue
        value = values[name]
        if name == "enabled":
            raw = "1" if value else "0"
        else:
            raw = str(value)
        SystemSetting.objects.update_or_create(
            setting_key=setting_key(prefix, name),
            defaults={"setting_value": raw, "updated_at": now, "updated_by": updated_by},
        )
    return get_config(prefix)


def _jitter(post_id: int, salt: str) -> float:
    """对帖子 ID 做哈希得到 0.90–1.10 的确定性抖动，刷新/重启都不变。"""
    digest = hashlib.sha1(f"{salt}:{int(post_id)}".encode("ascii")).hexdigest()
    return 0.90 + (int(digest[:8], 16) % 21) / 100.0


def _progress(age_seconds: float, grow_days: int) -> float:
    """到成长天数时约 95%，之后持平。"""
    return 1.0 - math.exp(-3.0 * (age_seconds / 86400.0) / max(1, grow_days))


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _override_value(override: dict | None, key: str, default: int = 0) -> int:
    if not override:
        return default
    raw = override.get(key, 0)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return default


def display_counts(
    real_views: int,
    real_likes: int,
    created_at,
    post_id: int,
    config: dict,
    override: dict | None = None,
    *,
    offset_days: float = 0,
) -> tuple[int, int]:
    """返回 (展示浏览, 展示赞)。

    override 为 None 时走全局开关；override 为 dict 时只要 enabled 就强制生效。
    quiet_minutes 内的新帖一律显示真实值。曲线只涨不落：成长到目标值后保持不变，
    不会因为帖子变旧而回落。

    停用（frozen_at 有值）时把进度冻结在停用那一刻，数字保持不变；
    只有显式「恢复真实数字」（删除设置）才会回落。
    """
    real_views = max(0, int(real_views or 0))
    real_likes = max(0, int(real_likes or 0))
    frozen = ""
    if override is not None:
        if not override.get("enabled") and not override.get("frozen_at"):
            return real_views, real_likes
        frozen = override.get("frozen_at") or ""
    else:
        if not config["enabled"] and not config.get("frozen_at"):
            return real_views, real_likes
        frozen = config.get("frozen_at") or ""

    age = max(0.0, (timezone.now() - _as_datetime(created_at)).total_seconds()) + float(offset_days) * 86400.0
    if age < config["quiet_minutes"] * 60:
        return real_views, real_likes
    if frozen:
        # 冻结：把年龄钳制在停用那一刻，曲线值保持不变。
        try:
            frozen_age = max(0.0, (_as_datetime(frozen) - _as_datetime(created_at)).total_seconds())
            age = min(age, frozen_age)
        except (TypeError, ValueError):
            pass

    target_views = _override_value(override, "target_views") or config["default_views"]
    grow_days = _override_value(override, "grow_days") or config["default_grow_days"]
    target_views = max(MIN_TARGET_VIEWS, min(int(target_views), MAX_TARGET_VIEWS))
    grow_days = max(1, min(int(grow_days), MAX_GROW_DAYS))
    target_likes = _override_value(override, "target_likes") or round(target_views * config["default_like_ratio"])

    progress = _progress(age, grow_days)
    views = max(real_views, int(round(target_views * progress * _jitter(post_id, "views"))))
    views = min(views, max(real_views, config["max_views"]))
    likes_cap = min(target_likes, views * config["max_like_ratio"])
    likes = max(real_likes, int(round(likes_cap * _jitter(post_id, "likes"))))
    return views, likes


def preview_pair(
    real_views: int,
    real_likes: int,
    created_at,
    post_id: int,
    config: dict,
    target_views: int,
    grow_days: int,
    target_likes: int,
    *,
    offset_days: float = 0,
) -> tuple[int, int]:
    """后台弹窗的实时预览：按「即将保存的配置」计算展示值。"""
    override = {
        "enabled": True,
        "target_views": int(target_views or 0),
        "grow_days": int(grow_days or 0),
        "target_likes": int(target_likes or 0),
    }
    return display_counts(real_views, real_likes, created_at, post_id, config, override, offset_days=offset_days)


def preview_set(real_views: int, real_likes: int, created_at, post_id: int, config: dict, values: dict) -> dict:
    """弹窗预览三连：现在 / 1 天后 / 成长天数后。"""
    enabled = bool(values.get("enabled", True))
    grow = int(values.get("grow_days") or 0) or config["default_grow_days"]
    result = {}
    for key, offset in (("now", 0), ("day1", 1), ("grow", grow)):
        if enabled:
            views, likes = preview_pair(
                real_views, real_likes, created_at, post_id, config,
                values.get("target_views", 0), values.get("grow_days", 0), values.get("target_likes", 0),
                offset_days=offset,
            )
        else:
            views, likes = max(0, int(real_views or 0)), max(0, int(real_likes or 0))
        result[key] = {"views": views, "likes": likes}
    result["grow_days"] = grow
    return result


def normalize_override_body(body: dict, config: dict) -> dict:
    """校验单帖设置表单；抛 ValueError 时直接把消息返回给前端。"""
    target_views = body.get("target_views", 0)
    if isinstance(target_views, bool) or not isinstance(target_views, int) or not (
        target_views == 0 or MIN_TARGET_VIEWS <= target_views <= MAX_TARGET_VIEWS
    ):
        raise ValueError(f"目标浏览需为 0（跟随全局）或 {MIN_TARGET_VIEWS}–{MAX_TARGET_VIEWS} 之间的整数")
    grow_days = body.get("grow_days", 0)
    if isinstance(grow_days, bool) or not isinstance(grow_days, int) or not (grow_days == 0 or 1 <= grow_days <= MAX_GROW_DAYS):
        raise ValueError(f"成长天数需为 0（跟随全局）或 1–{MAX_GROW_DAYS} 之间的整数")
    target_likes = body.get("target_likes", 0)
    if isinstance(target_likes, bool) or not isinstance(target_likes, int) or target_likes < 0:
        raise ValueError("目标赞数需为不小于 0 的整数（0 = 按比例自动换算）")
    if target_likes:
        view_base = target_views or config["default_views"]
        if target_likes > view_base * config["max_like_ratio"] + 1:
            raise ValueError(f"目标赞数不能超过展示浏览的 {int(config['max_like_ratio'] * 100)}%")
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > 200:
        raise ValueError("备注最多 200 字")
    enabled = body.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("启用状态无效")
    return {"target_views": target_views, "grow_days": grow_days, "target_likes": target_likes, "note": note.strip(), "enabled": enabled}


def normalize_settings_body(body: dict) -> dict:
    """校验全局设置面板；返回可直接 save_config 的值。"""
    values: dict = {}
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise ValueError("总开关状态无效")
        values["enabled"] = body["enabled"]
    for name, low, high, label in [
        ("default_views", MIN_TARGET_VIEWS, MAX_TARGET_VIEWS, "默认目标浏览"),
        ("default_grow_days", 1, MAX_GROW_DAYS, "默认成长天数"),
        ("quiet_minutes", 0, 1440, "新帖安静期（分钟）"),
        ("max_views", MIN_TARGET_VIEWS, 20000, "单帖浏览上限"),
    ]:
        if name not in body:
            continue
        value = body[name]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{label}需为 {low}–{high} 之间的整数")
        values[name] = value
    if "default_like_ratio" in body:
        value = body["default_like_ratio"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not RATIO_BOUNDS[0] <= float(value) <= RATIO_BOUNDS[1]:
            raise ValueError(f"默认点赞率需在 {RATIO_BOUNDS[0] * 100}%–{RATIO_BOUNDS[1] * 100}% 之间")
        values["default_like_ratio"] = round(float(value), 4)
    return values
