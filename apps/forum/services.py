# pyright: reportMissingImports=false
"""Forum domain services: hot score, boosts, deduplicated views."""
from __future__ import annotations

import json
import math
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from apps.catalog.models import SystemSetting
from apps.points.services import PointsError, apply_ledger, now_iso

from .models import ForumReply, ForumTopic, TopicBoost, TopicViewLog

# ── hot score ────────────────────────────────────────────────────────────────

HOT_WEIGHTS = {
    "like": 3.0,
    "reply": 5.0,
    "view": 0.2,
    "gravity": 1.2,
}
HOT_WEIGHT_KEYS = {
    "like": "forum.hot.like_weight",
    "reply": "forum.hot.reply_weight",
    "view": "forum.hot.view_weight",
    "gravity": "forum.hot.gravity",
}


def get_hot_weights() -> dict[str, float]:
    stored = dict(
        SystemSetting.objects.filter(setting_key__in=HOT_WEIGHT_KEYS.values())
        .values_list("setting_key", "setting_value")
    )
    result = dict(HOT_WEIGHTS)
    for name, key in HOT_WEIGHT_KEYS.items():
        raw = stored.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        result[name] = value
    return result


def compute_hot_score(topic: ForumTopic, *, likes: int, replies: int, views: int, weights=None) -> float:
    """hot = (likes*w + replies*w + views*w + active boost) * time decay."""
    weights = weights or get_hot_weights()
    base = (
        likes * weights["like"]
        + replies * weights["reply"]
        + views * weights["view"]
    )
    age_hours = max(0.0, (timezone.now() - topic.created_at).total_seconds() / 3600.0)
    decay = 1.0 / pow(age_hours + 2.0, weights["gravity"])
    return (base + topic.boost_score_active()) * decay


def refresh_hot_scores(topic_ids: list[int] | None = None) -> int:
    """Recompute hot_score for open topics (all when topic_ids is None)."""
    weights = get_hot_weights()
    qs = ForumTopic.objects.filter(status=ForumTopic.STATUS_OPEN)
    if topic_ids is not None:
        qs = qs.filter(id__in=topic_ids)
    topics = list(qs.only("id", "created_at", "views", "dedup_views"))
    like_counts = {
        row["id"]: row["cnt"]
        for row in qs.values("id").annotate(cnt=Count("likes"))
    }
    reply_counts = {
        row["topic_id"]: row["cnt"]
        for row in ForumReply.objects.filter(topic_id__in=[t.pk for t in topics], is_deleted=False)
        .values("topic_id")
        .annotate(cnt=Count("id"))
    }
    now = timezone.now()
    boost_totals: dict[int, int] = {}
    for boost in TopicBoost.objects.filter(status=TopicBoost.STATUS_ACTIVE, ends_at__gt=now, topic_id__in=[t.pk for t in topics]):
        boost_totals[boost.topic_id] = boost_totals.get(boost.topic_id, 0) + boost.boost_score
    updated = 0
    for topic in topics:
        base = (
            like_counts.get(topic.pk, 0) * weights["like"]
            + reply_counts.get(topic.pk, 0) * weights["reply"]
            + max(topic.views, topic.dedup_views) * weights["view"]
            + boost_totals.get(topic.pk, 0)
        )
        age_hours = max(0.0, (now - topic.created_at).total_seconds() / 3600.0)
        decay = 1.0 / pow(age_hours + 2.0, weights["gravity"])
        score = base * decay
        if topic.hot_score != score:
            ForumTopic.objects.filter(pk=topic.pk).update(hot_score=score)
        updated += 1
    # mark expired boosts ended
    TopicBoost.objects.filter(status=TopicBoost.STATUS_ACTIVE, ends_at__lte=now).update(
        status=TopicBoost.STATUS_ENDED
    )
    return updated


# ── boosts ───────────────────────────────────────────────────────────────────

BOOST_TIERS = {
    TopicBoost.TIER_SMALL: {"cost": 100, "score": 300, "hours": 24, "label": "小火"},
    TopicBoost.TIER_MEDIUM: {"cost": 300, "score": 1000, "hours": 48, "label": "中火"},
    TopicBoost.TIER_LARGE: {"cost": 1000, "score": 3600, "hours": 72, "label": "大火"},
}
BOOST_SETTING_KEYS = {
    tier: {
        "cost": f"forum.boost.{tier}.cost",
        "score": f"forum.boost.{tier}.score",
        "hours": f"forum.boost.{tier}.hours",
    }
    for tier in BOOST_TIERS
}
MAX_ACTIVE_BOOSTS_PER_TOPIC = 3


def get_boost_tiers() -> dict[str, dict]:
    stored = dict(
        SystemSetting.objects.filter(
            setting_key__in=[k for tier in BOOST_SETTING_KEYS.values() for k in tier.values()]
        ).values_list("setting_key", "setting_value")
    )
    tiers = {}
    for tier, defaults in BOOST_TIERS.items():
        entry = {"label": defaults["label"]}
        for field, default in defaults.items():
            if field == "label":
                continue
            raw = stored.get(BOOST_SETTING_KEYS[tier][field])
            try:
                entry[field] = int(raw) if raw is not None else default
            except (TypeError, ValueError):
                entry[field] = default
        entry["cost"] = max(0, entry["cost"])
        entry["score"] = max(0, entry["score"])
        entry["hours"] = max(1, entry["hours"])
        tiers[tier] = entry
    return tiers


def purchase_boost(*, user, topic: ForumTopic, tier: str) -> tuple[TopicBoost, dict]:
    tiers = get_boost_tiers()
    if tier not in tiers:
        raise PointsError("加热档位不存在")
    if topic.author_username != user.username:
        raise PointsError("只能给自己的帖子加热")
    if topic.status != ForumTopic.STATUS_OPEN:
        raise PointsError("帖子状态不允许加热")
    now = timezone.now()
    active = topic.boosts.filter(status=TopicBoost.STATUS_ACTIVE, ends_at__gt=now).count()
    if active >= MAX_ACTIVE_BOOSTS_PER_TOPIC:
        raise PointsError("该帖子的生效加热包已达上限（3 个）")
    spec = tiers[tier]
    with transaction.atomic():
        ledger, _ = apply_ledger(
            user=user,
            event_type="topic_boost",
            points_delta=-spec["cost"],
            idempotency_key=f"topic_boost:{user.pk}:{topic.pk}:{now_iso()}",
            description=f"帖子加热（{spec['label']}）：{topic.title[:50]}",
            reference_type="topic",
            reference_id=topic.pk,
        )
        boost = TopicBoost.objects.create(
            topic=topic,
            username=user.username,
            tier=tier,
            points_cost=spec["cost"],
            boost_score=spec["score"],
            starts_at=now,
            ends_at=now + timedelta(hours=spec["hours"]),
            status=TopicBoost.STATUS_ACTIVE,
            ledger_id=ledger.pk,
        )
        score = compute_hot_score(
            topic,
            likes=topic.likes.count(),
            replies=topic.reply_count,
            views=max(topic.views, topic.dedup_views),
        )
        ForumTopic.objects.filter(pk=topic.pk).update(hot_score=score)
    return boost, {"tier": tier, **spec, "ends_at": boost.ends_at.isoformat()}


def refund_active_boosts(topic: ForumTopic, *, reason: str = "topic removed") -> int:
    """Refund unexpired boosts proportionally when a topic is taken down."""
    from apps.accounts.models import User

    now = timezone.now()
    refunded = 0
    for boost in topic.boosts.filter(status=TopicBoost.STATUS_ACTIVE, ends_at__gt=now):
        try:
            user = User.objects.get(username=boost.username)
        except User.DoesNotExist:
            continue
        total_seconds = max(1.0, (boost.ends_at - boost.starts_at).total_seconds())
        remaining = max(0.0, (boost.ends_at - now).total_seconds()) / total_seconds
        amount = int(boost.points_cost * remaining)
        if amount > 0:
            apply_ledger(
                user=user,
                event_type="topic_boost_refund",
                points_delta=amount,
                idempotency_key=f"topic_boost_refund:{boost.pk}",
                description=f"帖子下线，加热按剩余时长退还：{reason}",
                reference_type="topic_boost",
                reference_id=boost.pk,
            )
        boost.status = TopicBoost.STATUS_REFUNDED
        boost.save(update_fields=["status"])
        refunded += 1
    return refunded


# ── deduplicated views ───────────────────────────────────────────────────────

def record_dedup_view(topic: ForumTopic, viewer_key: str) -> bool:
    """+1 dedup_views for the first view of this viewer today; returns True when counted."""
    view_date = timezone.localdate().isoformat()
    viewer_key = (viewer_key or "anon")[:180]
    try:
        _, created = TopicViewLog.objects.get_or_create(
            topic=topic, viewer_key=viewer_key, view_date=view_date
        )
    except Exception:
        return False
    if created:
        ForumTopic.objects.filter(pk=topic.pk).update(dedup_views=F("dedup_views") + 1)
    return created


def parse_image_ids(raw: str) -> list[int]:
    try:
        data = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [int(x) for x in data if isinstance(x, (int, float, str)) and str(x).strip().isdigit()][:9]
