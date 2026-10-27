"""终端配对、令牌与摘要数据的组装。"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.catalog.models import SystemSetting
from apps.gamification.models import UserAchievement, UserStats
from apps.notifications.models import Notification
from apps.points.models import PointAccount, UserDailyActivity
from apps.points.services import SITE_TZ, award_daily_activity, get_rules

from .models import TerminalDevice

# 去掉易混淆字符（0/O、1/I/L、2/Z），终端只用手输或屏幕显示，必须能一眼念对。
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXY3456789"
TOKEN_BYTES = 32

SETTING_PAIR_TTL = "terminal.pair.ttl_seconds"
SETTING_REFRESH = "terminal.refresh.seconds"
SETTING_PAIRING_ENABLED = "terminal.pairing.enabled"

DEFAULT_PAIR_TTL = 600
DEFAULT_REFRESH = 300

# 固件只有 ASCII 字体，服务端把中文类型折成短标签，屏幕端不再维护一套映射。
TYPE_LABELS = {
    "badge": "BADGE",
    "level": "LEVEL",
    "like": "LIKE",
    "reply": "REPLY",
    "reply_like": "R-LIKE",
    "mention": "MENTION",
    "message": "MESSAGE",
    "sale": "SALE",
    "feed": "FEED",
    "imaging": "IMAGING",
    "system": "SYSTEM",
}


def _setting_int(key: str, default: int, *, low: int, high: int) -> int:
    raw = SystemSetting.objects.filter(setting_key=key).values_list("setting_value", flat=True).first()
    try:
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def refresh_seconds() -> int:
    return _setting_int(SETTING_REFRESH, DEFAULT_REFRESH, low=60, high=3600)


def newest_id(user) -> int:
    """该用户最新一条通知的 id，没有就是 0。

    终端不存任何通知正文，只存这个整数当「水位线」：比它大 = 有新的到过。
    用 id 而不是时间戳，是因为 id 单调递增且不会因为时区/时钟漂移而倒退。
    """
    return int(
        Notification.objects.filter(recipient=user).order_by("-id").values_list("id", flat=True).first()
        or 0
    )


def pair_ttl_seconds() -> int:
    return _setting_int(SETTING_PAIR_TTL, DEFAULT_PAIR_TTL, low=60, high=1800)


def pairing_enabled() -> bool:
    raw = SystemSetting.objects.filter(setting_key=SETTING_PAIRING_ENABLED).values_list("setting_value", flat=True).first()
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_token(device: TerminalDevice) -> str:
    """签发新令牌，返回明文（仅此一次），库里只留摘要与可读前缀。"""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    device.token_hash = hash_token(raw)
    device.token_prefix = raw[:8]
    device.token_issued_at = timezone.now()
    device.token_delivered_at = None
    return raw


def new_pairing_code() -> str:
    now = timezone.now()
    for _ in range(12):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        taken = TerminalDevice.objects.filter(
            pairing_code=code,
            status="pending",
            pairing_expires_at__gt=now,
        ).exists()
        if not taken:
            return code
    raise RuntimeError("pairing code space exhausted")


def checked_in_today(user) -> bool:
    """今天是否已经记过有效访问。与网页端打卡共用 user_daily_activity 这一天表。"""
    today = timezone.now().astimezone(SITE_TZ).date().isoformat()
    return UserDailyActivity.objects.filter(user=user, activity_date=today).exists()


def checkin_payload(user) -> dict:
    """屏幕点一下「签到」= 今天首次有效访问。

    不新造积分事件，直接复用 award_daily_activity：它自带按天幂等
    （user_daily_activity 的唯一约束），所以连点、双端同时点都只会发一次分。
    """
    rules = get_rules()
    # 发分那条链路里有 select_for_update，必须在事务里跑，否则直接抛
    # TransactionManagementError。连点两下会同时进来，也正好靠这层串行化。
    with transaction.atomic():
        ledger, awarded = award_daily_activity(user)
    account = PointAccount.objects.filter(user=user).first()
    return {
        "ok": True,
        "awarded": bool(awarded),
        "points": int(ledger.delta) if (awarded and ledger is not None) else 0,
        "balance": int(account.balance) if account else 0,
        "streak": int(account.consecutive_active_days) if account else 0,
        "reward": int(rules["daily_activity_reward"]),
        "done": True,
    }


def summary_payload(device: TerminalDevice) -> dict:
    """组装「看一眼就够」的账号摘要。全程只读。"""
    user = device.user
    account = PointAccount.objects.filter(user=user).first()
    stats = UserStats.objects.filter(user=user).first()

    unread_qs = Notification.objects.filter(recipient=user, is_read=False)
    unread = unread_qs.count()
    recent = list(unread_qs.order_by("-created_at", "-id")[:3])
    if not recent:
        recent = list(Notification.objects.filter(recipient=user).order_by("-created_at", "-id")[:3])

    badges = UserAchievement.objects.filter(user=user).count()
    now = timezone.now()

    return {
        "ok": True,
        "server_time": now.isoformat(),
        # UTC 秒。终端没有 RTC，靠这个对时比解析 ISO 字符串可靠：
        # server_time 带 +00:00 偏移，固件自己换算容易差 8 小时。
        "epoch": int(now.timestamp()),
        "user": {
            "username": user.username,
            "display_name": user.display_name or user.username,
        },
        "points": {
            "balance": int(account.balance) if account else 0,
            "total_earned": int(account.total_earned) if account else 0,
            "total_spent": int(account.total_spent) if account else 0,
            "reputation_level": int(account.reputation_level) if account else 0,
            "streak": int(account.consecutive_active_days) if account else 0,
        },
        "notifications": {
            "unread": unread,
            # 设备靠这个整数判断「有没有新的」：它自己存一份上次见过的 id，
            # 数字变大才亮提醒。不给 id 的话，设备只能比标题——标题相同就漏报。
            # 取全表最大，不看已读状态：读掉之后 id 不变，设备才不会又弹一次。
            "latest_id": newest_id(user),
            "items": [
                {
                    "id": row.id,
                    "type": row.type,
                    "label": TYPE_LABELS.get(row.type, "SYSTEM"),
                    "title": row.title,
                    "is_read": bool(row.is_read),
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
                for row in recent
            ],
        },
        "community": {
            "topics": int(stats.topics) if stats else 0,
            "replies": int(stats.replies) if stats else 0,
            "likes_received": stats.total_likes_received if stats else 0,
            "badges": badges,
            "active_days": int(stats.active_days) if stats else 0,
        },
        # 签到状态随摘要下发：屏幕顶端那一带要不要显示 CHECKED IN 全看这里，
        # 免得固件自己算日期（终端没有 RTC，跨天判断一律不可信）。
        "checkin": {
            "done": checked_in_today(user),
            "reward": int(get_rules()["daily_activity_reward"]),
        },
        "device": {
            "name": device.name or device.device_id,
            "firmware": device.firmware,
            "sync_count": int(device.sync_count),
        },
        "refresh_seconds": refresh_seconds(),
    }


def touch_device(device: TerminalDevice, *, ip: str = "") -> None:
    """记录心跳，避免并发请求互相覆盖计数。"""
    TerminalDevice.objects.filter(pk=device.pk).update(
        last_seen_at=timezone.now(),
        last_ip=ip,
        sync_count=F("sync_count") + 1,
    )


def pairing_expiry() -> datetime:
    return timezone.now() + timedelta(seconds=pair_ttl_seconds())
