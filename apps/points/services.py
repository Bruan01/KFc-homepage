"""Transactional Django ORM implementation of KFlow point awards."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from django.db import IntegrityError
from django.utils import timezone

from apps.catalog.models import SystemSetting
from .models import PointAccount, PointLedger, UserDailyActivity

SITE_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_RULES = {
    "registration_reward": 20,
    "registration_contribution": 10,
    "daily_activity_reward": 2,
    "daily_activity_contribution": 1,
}
SETTING_KEYS = {
    "registration_reward": "points.registration.reward",
    "registration_contribution": "points.registration.contribution",
    "daily_activity_reward": "points.daily_activity.reward",
    "daily_activity_contribution": "points.daily_activity.contribution",
}


def now_iso():
    return timezone.now().isoformat()


def get_rule(name):
    default = DEFAULT_RULES[name]
    raw = SystemSetting.objects.filter(pk=SETTING_KEYS[name]).values_list("setting_value", flat=True).first()
    try:
        return max(0, int(raw)) if raw is not None else default
    except (TypeError, ValueError):
        return default


def ensure_account(user):
    account, _ = PointAccount.objects.get_or_create(user=user, defaults={"updated_at": now_iso()})
    return PointAccount.objects.select_for_update().get(pk=account.pk)


def apply_ledger(*, user, event_type, points_delta, contribution_delta, idempotency_key, description, reference_type, reference_id):
    existing = PointLedger.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing, False
    account = ensure_account(user)
    if account.status != "active":
        return None, False
    balance = int(account.balance or 0) + int(points_delta)
    if balance < 0:
        return None, False
    contribution = max(0, int(account.contribution_score or 0) + int(contribution_delta))
    account.balance = balance
    account.total_earned = int(account.total_earned or 0) + max(0, int(points_delta))
    account.total_spent = int(account.total_spent or 0) + max(0, -int(points_delta))
    account.contribution_score = contribution
    account.updated_at = now_iso()
    account.save(update_fields=["balance", "total_earned", "total_spent", "contribution_score", "updated_at"])
    ledger = PointLedger.objects.create(
        user=user,
        event_type=event_type,
        delta=int(points_delta),
        balance_after=balance,
        contribution_delta=int(contribution_delta),
        reference_type=reference_type,
        reference_id=str(reference_id),
        idempotency_key=idempotency_key,
        description=description,
        created_by="system",
        created_at=now_iso(),
    )
    return ledger, True


def award_registration(user):
    return apply_ledger(
        user=user,
        event_type="registration_reward",
        points_delta=get_rule("registration_reward"),
        contribution_delta=get_rule("registration_contribution"),
        idempotency_key=f"registration_reward:{user.pk}",
        description="邮箱验证注册奖励",
        reference_type="user",
        reference_id=user.pk,
    )


def award_daily_activity(user):
    activity_date = timezone.now().astimezone(SITE_TZ).date().isoformat()
    try:
        _, created = UserDailyActivity.objects.get_or_create(
            user=user,
            activity_date=activity_date,
            defaults={"created_at": now_iso()},
        )
    except IntegrityError:
        created = False
    if not created:
        return None, False
    ledger, awarded = apply_ledger(
        user=user,
        event_type="daily_activity",
        points_delta=get_rule("daily_activity_reward"),
        contribution_delta=get_rule("daily_activity_contribution"),
        idempotency_key=f"daily_activity:{user.pk}:{activity_date}",
        description="每日首次有效访问",
        reference_type="activity_date",
        reference_id=activity_date,
    )
    PointAccount.objects.filter(pk=user.pk).update(last_active_date=activity_date, updated_at=now_iso())
    return ledger, awarded
