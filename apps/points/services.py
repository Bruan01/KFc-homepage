"""Transactional Django ORM implementation of KFlow points."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from http import HTTPStatus
from zoneinfo import ZoneInfo

from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import Product, SystemSetting
from apps.downloads.models import Download, DownloadEntitlement, DownloadRequest
from .models import PointAccount, PointLedger, UserDailyActivity

SITE_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_RULES = {
    "registration_reward": 20,
    "registration_contribution": 10,
    "daily_activity_reward": 2,
    "daily_activity_contribution": 1,
    "download_default_cost": 10,
    "download_entitlement_ttl_hours": 24,
    "download_redemption_enabled": True,
    "image_generation_default_cost": 10,
    "forum_topic_reward": 10,
    "forum_topic_contribution": 5,
    "forum_topic_daily_cap": 3,
    "forum_reply_reward": 2,
    "forum_reply_contribution": 1,
    "forum_reply_daily_cap": 10,
    "forum_like_received_reward": 1,
    "forum_like_received_contribution": 1,
    "forum_like_received_daily_cap": 50,
    "forum_reply_like_received_reward": 1,
    "forum_reply_like_received_contribution": 0,
    "forum_reply_like_received_daily_cap": 20,
}
SETTING_KEYS = {
    "registration_reward": "points.registration.reward",
    "registration_contribution": "points.registration.contribution",
    "daily_activity_reward": "points.daily_activity.reward",
    "daily_activity_contribution": "points.daily.activity.contribution",
    "download_default_cost": "points.download.default_cost",
    "download_entitlement_ttl_hours": "points.download.entitlement_ttl_hours",
    "download_redemption_enabled": "points.download.redemption_enabled",
    "image_generation_default_cost": "points.image_generation.default_cost",
    "forum_topic_reward": "points.forum.topic_reward",
    "forum_topic_contribution": "points.forum.topic_contribution",
    "forum_topic_daily_cap": "points.forum.topic_daily_cap",
    "forum_reply_reward": "points.forum.reply_reward",
    "forum_reply_contribution": "points.forum.reply_contribution",
    "forum_reply_daily_cap": "points.forum.reply_daily_cap",
    "forum_like_received_reward": "points.forum.like_received_reward",
    "forum_like_received_contribution": "points.forum.like_received_contribution",
    "forum_like_received_daily_cap": "points.forum.like_received_daily_cap",
    "forum_reply_like_received_reward": "points.forum.reply_like_received_reward",
    "forum_reply_like_received_contribution": "points.forum.reply_like_received_contribution",
    "forum_reply_like_received_daily_cap": "points.forum.reply_like_received_daily_cap",
}


class PointsError(Exception):
    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = int(status)


def now_iso():
    return timezone.now().isoformat()


def get_rules():
    stored = dict(SystemSetting.objects.filter(setting_key__in=SETTING_KEYS.values()).values_list("setting_key", "setting_value"))
    result = {}
    for name, default in DEFAULT_RULES.items():
        raw = stored.get(SETTING_KEYS[name])
        if isinstance(default, bool):
            result[name] = default if raw is None else str(raw).strip().lower() in {"1", "true", "yes", "on"}
        else:
            try:
                result[name] = int(raw) if raw is not None else default
            except (TypeError, ValueError):
                result[name] = default
    for name in ("registration_reward", "registration_contribution", "daily_activity_reward", "daily_activity_contribution", "download_default_cost", "image_generation_default_cost"):
        result[name] = max(0, result[name])
    result["download_entitlement_ttl_hours"] = max(1, result["download_entitlement_ttl_hours"])
    return result


def save_rules(values, updated_by):
    for name, default in DEFAULT_RULES.items():
        if name not in values:
            continue
        if isinstance(default, bool):
            stored = "true" if bool(values[name]) else "false"
        else:
            try:
                value = int(values[name])
            except (TypeError, ValueError) as exc:
                raise PointsError(f"invalid rule: {name}") from exc
            if value < 0:
                raise PointsError(f"rule must be non-negative: {name}")
            if name == "download_entitlement_ttl_hours" and value < 1:
                raise PointsError("download entitlement TTL must be at least 1 hour")
            stored = str(value)
        SystemSetting.objects.update_or_create(
            setting_key=SETTING_KEYS[name],
            defaults={"setting_value": stored, "updated_at": now_iso(), "updated_by": updated_by},
        )
    return get_rules()


def ensure_account(user):
    PointAccount.objects.get_or_create(user=user, defaults={"updated_at": now_iso()})
    return PointAccount.objects.select_for_update().get(pk=user.pk)


def apply_ledger(*, user, event_type, points_delta, contribution_delta=0, idempotency_key, description="", reference_type="", reference_id="", created_by="system", allow_frozen=False):
    existing = PointLedger.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing, False
    account = ensure_account(user)
    if account.status != "active" and not allow_frozen:
        raise PointsError("points account frozen", HTTPStatus.FORBIDDEN)
    points_delta = int(points_delta)
    contribution_delta = int(contribution_delta)
    balance = int(account.balance or 0) + points_delta
    if balance < 0:
        raise PointsError("insufficient points", HTTPStatus.CONFLICT)
    account.balance = balance
    account.total_earned = int(account.total_earned or 0) + max(0, points_delta)
    account.total_spent = int(account.total_spent or 0) + max(0, -points_delta)
    account.contribution_score = max(0, int(account.contribution_score or 0) + contribution_delta)
    account.updated_at = now_iso()
    account.save(update_fields=["balance", "total_earned", "total_spent", "contribution_score", "updated_at"])
    ledger = PointLedger.objects.create(
        user=user,
        event_type=event_type,
        delta=points_delta,
        balance_after=balance,
        contribution_delta=contribution_delta,
        reference_type=reference_type,
        reference_id=str(reference_id or ""),
        idempotency_key=idempotency_key,
        description=description,
        created_by=created_by,
        created_at=now_iso(),
    )
    return ledger, True


def award_registration(user):
    rules = get_rules()
    return apply_ledger(
        user=user,
        event_type="registration_reward",
        points_delta=rules["registration_reward"],
        contribution_delta=rules["registration_contribution"],
        idempotency_key=f"registration_reward:{user.pk}",
        description="邮箱验证注册奖励",
        reference_type="user",
        reference_id=user.pk,
    )


def award_daily_activity(user):
    activity_date = timezone.now().astimezone(SITE_TZ).date().isoformat()
    try:
        _, created = UserDailyActivity.objects.get_or_create(user=user, activity_date=activity_date, defaults={"created_at": now_iso()})
    except IntegrityError:
        created = False
    if not created:
        return None, False
    rules = get_rules()
    ledger, awarded = apply_ledger(
        user=user,
        event_type="daily_activity",
        points_delta=rules["daily_activity_reward"],
        contribution_delta=rules["daily_activity_contribution"],
        idempotency_key=f"daily_activity:{user.pk}:{activity_date}",
        description="每日首次有效访问",
        reference_type="activity_date",
        reference_id=activity_date,
    )
    PointAccount.objects.filter(pk=user.pk).update(last_active_date=activity_date, updated_at=now_iso())
    return ledger, awarded


# ── forum activity rewards (daily-capped, idempotent per object) ─────────────


def _local_day_start_utc_iso() -> str:
    local_now = timezone.now().astimezone(SITE_TZ)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start.astimezone(dt_timezone.utc).isoformat()


def award_forum_activity(
    *,
    user,
    event_type: str,
    reward_key: str,
    contribution_key: str,
    cap_key: str,
    description: str,
    idempotency_key: str,
    reference_type: str = "",
    reference_id: str | int = "",
) -> tuple[PointLedger | None, bool]:
    """Award forum activity points, skipping silently once the daily cap is hit.

    Idempotency key must be unique per rewarded object (topic/reply/like id),
    so repeat triggers for the same object never double-award.
    """
    rules = get_rules()
    reward = max(0, rules[reward_key])
    if reward <= 0:
        return None, False
    cap = max(0, rules[cap_key])
    if cap > 0:
        today_count = PointLedger.objects.filter(
            user=user,
            event_type=event_type,
            created_at__gte=_local_day_start_utc_iso(),
        ).count()
        if today_count >= cap:
            return None, False
    return apply_ledger(
        user=user,
        event_type=event_type,
        points_delta=reward,
        contribution_delta=rules[contribution_key],
        idempotency_key=idempotency_key,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
    )


def award_topic_created(user, topic_id):
    return award_forum_activity(
        user=user,
        event_type="topic_created",
        reward_key="forum_topic_reward",
        contribution_key="forum_topic_contribution",
        cap_key="forum_topic_daily_cap",
        description="发布作品帖",
        idempotency_key=f"topic_created:{user.pk}:{topic_id}",
        reference_type="topic",
        reference_id=topic_id,
    )


def award_reply_created(user, reply_id):
    return award_forum_activity(
        user=user,
        event_type="reply_created",
        reward_key="forum_reply_reward",
        contribution_key="forum_reply_contribution",
        cap_key="forum_reply_daily_cap",
        description="发表评论",
        idempotency_key=f"reply_created:{user.pk}:{reply_id}",
        reference_type="forum_reply",
        reference_id=reply_id,
    )


def award_like_received(user, *, liker_username: str, kind: str, object_id):
    """+points when someone likes the user's topic/reply. Self-likes never award."""
    if not user or liker_username == user.username:
        return None, False
    if kind == "reply":
        return award_forum_activity(
            user=user,
            event_type="reply_like_received",
            reward_key="forum_reply_like_received_reward",
            contribution_key="forum_reply_like_received_contribution",
            cap_key="forum_reply_like_received_daily_cap",
            description="评论被点赞",
            idempotency_key=f"reply_like_received:{user.pk}:{object_id}",
            reference_type="forum_reply",
            reference_id=object_id,
        )
    return award_forum_activity(
        user=user,
        event_type="like_received",
        reward_key="forum_like_received_reward",
        contribution_key="forum_like_received_contribution",
        cap_key="forum_like_received_daily_cap",
        description="作品被点赞",
        idempotency_key=f"like_received:{user.pk}:{object_id}",
        reference_type="topic",
        reference_id=object_id,
    )


def account_payload(user):
    account = ensure_account(user)
    return {
        "balance": int(account.balance or 0),
        "totalEarned": int(account.total_earned or 0),
        "totalSpent": int(account.total_spent or 0),
        "contributionScore": int(account.contribution_score or 0),
        "reputationLevel": int(account.reputation_level or 0),
        "status": account.status,
        "lastActiveDate": account.last_active_date or "",
    }


def product_download_cost(product):
    rules = get_rules()
    if not rules["download_redemption_enabled"] or not bool(product.points_redemption_enabled):
        return None
    return rules["download_default_cost"] if product.point_download_cost is None else max(0, int(product.point_download_cost))


def active_entitlement(user, product):
    return DownloadEntitlement.objects.filter(
        user=user, product=product, remaining_count__gt=0, consumed_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now_iso())).order_by("-id").first()


def redeem_download(*, user, product_id, idempotency_key):
    idem = str(idempotency_key or "").strip()
    if len(idem) < 8 or len(idem) > 160:
        raise PointsError("valid idempotency key required")
    existing = DownloadEntitlement.objects.filter(idempotency_key=idem).first()
    if existing:
        if existing.user_id != user.pk:
            raise PointsError("idempotency key conflict", HTTPStatus.CONFLICT)
        return existing, account_payload(user), False
    product = Product.objects.filter(pk=product_id, status="published").first()
    if not product:
        raise PointsError("published product not found", HTTPStatus.NOT_FOUND)
    if not product.file_path and not product.packages.exclude(file_path__isnull=True).exclude(file_path="").exists():
        raise PointsError("product file unavailable", HTTPStatus.CONFLICT)
    if not Download.objects.filter(product=product, user=user).exists():
        raise PointsError("free download still available", HTTPStatus.CONFLICT)
    if DownloadRequest.objects.filter(product=product, user=user, status="approved", consumed_at__isnull=True).exists():
        raise PointsError("approved download already available", HTTPStatus.CONFLICT)
    if active_entitlement(user, product):
        raise PointsError("unused download entitlement already exists", HTTPStatus.CONFLICT)
    cost = product_download_cost(product)
    if cost is None:
        raise PointsError("points redemption disabled for product", HTTPStatus.FORBIDDEN)
    ledger, _ = apply_ledger(
        user=user,
        event_type="download_redemption",
        points_delta=-cost,
        idempotency_key=f"download_redemption:{idem}",
        description=f"兑换产品额外下载：{product.name}",
        reference_type="product",
        reference_id=product.pk,
    )
    created = timezone.now()
    entitlement = DownloadEntitlement.objects.create(
        user=user,
        product=product,
        source="points",
        point_ledger=ledger,
        cost=cost,
        remaining_count=1,
        idempotency_key=idem,
        created_at=created.isoformat(),
        expires_at=(created + timedelta(hours=get_rules()["download_entitlement_ttl_hours"])).isoformat(),
    )
    return entitlement, account_payload(user), True


def ledger_payload(row):
    return {
        "id": row.pk,
        "eventType": row.event_type,
        "delta": int(row.delta),
        "balanceAfter": int(row.balance_after),
        "contributionDelta": int(row.contribution_delta or 0),
        "referenceType": row.reference_type or "",
        "referenceId": row.reference_id or "",
        "description": row.description or "",
        "status": row.status,
        "createdBy": row.created_by,
        "createdAt": row.created_at,
    }
