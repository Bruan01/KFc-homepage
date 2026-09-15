# pyright: reportMissingImports=false
"""Gamification services: user stats, achievements, trust levels.

参照 Discourse 信任等级与 Stack Overflow 勋章体系：
- 勋章基于单用户实时聚合统计自动授予（幂等）；
- 等级基于统计快照只升不降，LV4 仅人工授予；
- 每小时批量刷新快照与等级（由 rankings 的 refresh 定时任务一并调用）。
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.points.models import PointAccount, UserDailyActivity

from .models import Achievement, UserAchievement, UserStats

# ── 等级定义（LV0-LV4，参照 Discourse 信任等级） ─────────────────────────────

LEVELS: list[dict[str, Any]] = [
    {
        "level": 0,
        "name": "新用户",
        "requirements": {},
        "requirements_text": "注册即得",
        "perks": ["浏览、发帖、评论、点赞、积分兑换"],
    },
    {
        "level": 1,
        "name": "正式成员",
        "requirements": {"active_days": 3, "topics": 1},
        "requirements_text": "活跃 ≥3 天 且 发帖 ≥1（或评论 ≥3）",
        "perks": ["解锁 kflowstore 创作者货架上架权限"],
    },
    {
        "level": 2,
        "name": "活跃成员",
        "requirements": {"active_days": 7, "topics": 3, "likes_received": 10},
        "requirements_text": "活跃 ≥7 天 且 发帖 ≥3 且 获赞 ≥10",
        "perks": ["发帖积分日上限放宽（3 帖 → 5 帖）"],
    },
    {
        "level": 3,
        "name": "贡献者",
        "requirements": {"active_days": 30, "topics": 10, "likes_received": 50, "contribution": 200},
        "requirements_text": "活跃 ≥30 天 且 发帖 ≥10 且 获赞 ≥50 且 贡献分 ≥200",
        "perks": ["加热 9 折（二期）", "社区治理候选"],
    },
    {
        "level": 4,
        "name": "核心成员",
        "requirements": None,
        "requirements_text": "管理员人工授予",
        "perks": ["参与社区治理与审批投票", "内部测试资格"],
    },
]

# LV2/LV3 的发帖积分日上限放宽（供 points 侧读取）
TOPIC_DAILY_CAP_BY_LEVEL = {0: None, 1: None, 2: 5, 3: 8, 4: 8}


def level_config(level: int) -> dict[str, Any]:
    for entry in LEVELS:
        if entry["level"] == level:
            return entry
    return LEVELS[0]


# ── 用户统计 ────────────────────────────────────────────────────────────────


def compute_user_stats(user: User) -> dict[str, int]:
    """Live aggregation of one user's community counters (cheap count queries)."""
    from apps.forum.models import ForumLike, ForumReply, ForumReplyLike, ForumTopic, TopicBoost
    from apps.rankings.models import ExternalProjectVote
    from apps.store.models import ListingRedemption

    topics = ForumTopic.objects.filter(author_username=user.username, status=ForumTopic.STATUS_OPEN)
    replies = ForumReply.objects.filter(
        author_username=user.username, is_deleted=False, topic__status=ForumTopic.STATUS_OPEN
    )
    max_topic_likes = max(
        topics.annotate(like_count=Count("likes", distinct=True)).values_list("like_count", flat=True),
        default=0,
    )
    return {
        "active_days": UserDailyActivity.objects.filter(user=user).values("activity_date").distinct().count(),
        "topics": topics.count(),
        "replies": replies.count(),
        "likes_given": ForumLike.objects.filter(username=user.username).count()
        + ForumReplyLike.objects.filter(username=user.username).count(),
        "likes_received": ForumLike.objects.filter(topic__author_username=user.username).count(),
        "reply_likes_received": ForumReplyLike.objects.filter(reply__author_username=user.username).count(),
        "votes_cast": ExternalProjectVote.objects.filter(username=user.username).count(),
        "boosts_bought": TopicBoost.objects.filter(username=user.username).count(),
        "listings_sold": ListingRedemption.objects.filter(seller_username=user.username).count(),
        "max_topic_likes": max_topic_likes,
        "tutorials_completed": _learn_completed(user, "tutorial"),
        "terms_completed": _learn_completed(user, "term"),
    }


def _learn_completed(user, kind: str) -> int:
    try:
        from apps.learn.models import LearnProgress

        return LearnProgress.objects.filter(user=user, kind=kind).count()
    except Exception:
        return 0


def refresh_user_stats_table() -> int:
    """Bulk refresh the UserStats snapshot for all users with any activity."""
    updated = 0
    for user in User.objects.all().iterator():
        stats = compute_user_stats(user)
        row, _ = UserStats.objects.update_or_create(user=user, defaults=stats)
        updated += 1
    return updated


# ── 等级 ────────────────────────────────────────────────────────────────────


def _requirements_met(req: dict[str, int], stats: dict[str, int], contribution: int) -> bool:
    for key, threshold in req.items():
        value = contribution if key == "contribution" else stats.get(key, 0)
        if value < threshold:
            return False
    return True


def compute_level(stats: dict[str, int], contribution: int, current: int) -> int:
    """Highest auto level whose requirements are met; never demotes; LV4 manual."""
    earned = 0
    for entry in LEVELS:
        req = entry["requirements"]
        if entry["level"] == 4 or req is None:
            continue
        if _requirements_met(req, stats, contribution):
            earned = entry["level"]
    # LV1 也接受「评论 ≥3」作为发帖条件的替代
    if earned < 1 and stats.get("active_days", 0) >= 3 and (
        stats.get("replies", 0) >= 3 or stats.get("topics", 0) >= 1
    ):
        earned = 1
    return max(earned, current)  # 只升不降


def promote_user_level(user: User, *, stats: dict[str, int] | None = None) -> int:
    account, _ = PointAccount.objects.get_or_create(user=user, defaults={"updated_at": timezone.now().isoformat()})
    if stats is None:
        stats = compute_user_stats(user)
    old_level = int(account.reputation_level or 0)
    new_level = compute_level(stats, int(account.contribution_score or 0), old_level)
    if new_level != old_level:
        account.reputation_level = new_level
        account.save(update_fields=["reputation_level"])
        if new_level > old_level:
            from apps.notifications.services import notify

            entry = level_config(new_level)
            notify(
                recipient=user, type_="level",
                title=f"等级提升：你已升级到 LV{new_level} {entry["name"]}",
                body="；".join(entry.get("perks", []))[:280],
                link="/levels",
            )
    return new_level


def refresh_all_levels() -> int:
    changed = 0
    for account in PointAccount.objects.select_related("user").iterator():
        stats = compute_user_stats(account.user)
        old_level = int(account.reputation_level or 0)
        new_level = compute_level(stats, int(account.contribution_score or 0), old_level)
        if new_level != old_level:
            account.reputation_level = new_level
            account.save(update_fields=["reputation_level"])
            changed += 1
            if new_level > old_level:
                from apps.notifications.services import notify

                entry = level_config(new_level)
                notify(
                    recipient=account.user, type_="level",
                    title=f"等级提升：你已升级到 LV{new_level} {entry["name"]}",
                    body="；".join(entry.get("perks", []))[:280],
                    link="/levels",
                )
    return changed


# ── 成就勋章 ────────────────────────────────────────────────────────────────

# 判定规则：(code, stats key / special) —— special 用 lambda 读统计字典
def _learning_catalog_size(kind: str, fallback: int) -> int:
    """Read the authored learning catalog size so "全部" badges stay accurate."""
    try:
        if kind == "tutorial":
            from apps.learn.tutorials_data import TUTORIALS

            return len(TUTORIALS)
        if kind == "term":
            from apps.learn.glossary_data import GLOSSARY

            return len(GLOSSARY)
    except Exception:
        pass
    return fallback


BADGE_RULES: list[dict[str, Any]] = [
    {"code": "first_post", "check": lambda s, c: s["topics"] >= 1},
    {"code": "first_reply", "check": lambda s, c: s["replies"] >= 1},
    {"code": "first_like", "check": lambda s, c: s["likes_given"] >= 1},
    {"code": "regular_3", "check": lambda s, c: s["active_days"] >= 3},
    {"code": "first_vote", "check": lambda s, c: s["votes_cast"] >= 1},
    {"code": "first_boost", "check": lambda s, c: s["boosts_bought"] >= 1},
    {"code": "author_10", "check": lambda s, c: s["topics"] >= 10},
    {"code": "liked_25", "check": lambda s, c: s["likes_received"] + s["reply_likes_received"] >= 25},
    {"code": "helper_50", "check": lambda s, c: s["replies"] >= 50},
    {"code": "veteran_14", "check": lambda s, c: s["active_days"] >= 14},
    {"code": "notable_work", "check": lambda s, c: s["max_topic_likes"] >= 10},
    {"code": "seller_first", "check": lambda s, c: s["listings_sold"] >= 1},
    {"code": "liked_100", "check": lambda s, c: s["likes_received"] + s["reply_likes_received"] >= 100},
    {"code": "pillar_500", "check": lambda s, c: c >= 500},
    {"code": "ancient_100", "check": lambda s, c: s["active_days"] >= 100},
    {"code": "famous_work", "check": lambda s, c: s["max_topic_likes"] >= 50},
    {"code": "boost_10", "check": lambda s, c: s["boosts_bought"] >= 10},
    {"code": "voter_50", "check": lambda s, c: s["votes_cast"] >= 50},
    {"code": "active_7", "check": lambda s, c: s["active_days"] >= 7},
    {"code": "author_3", "check": lambda s, c: s["topics"] >= 3},
    {"code": "reply_10", "check": lambda s, c: s["replies"] >= 10},
    {"code": "likes_given_10", "check": lambda s, c: s["likes_given"] >= 10},
    {"code": "vote_10", "check": lambda s, c: s["votes_cast"] >= 10},
    {"code": "boost_3", "check": lambda s, c: s["boosts_bought"] >= 3},
    {"code": "active_30", "check": lambda s, c: s["active_days"] >= 30},
    {"code": "reply_likes_10", "check": lambda s, c: s["reply_likes_received"] >= 10},
    {"code": "notable_work_25", "check": lambda s, c: s["max_topic_likes"] >= 25},
    {"code": "study_6", "check": lambda s, c: s["tutorials_completed"] >= 6},
    {"code": "dict_5", "check": lambda s, c: s["terms_completed"] >= 5},
    {"code": "seller_5", "check": lambda s, c: s["listings_sold"] >= 5},
    {"code": "contributor_1000", "check": lambda s, c: c >= 1000},
    {"code": "liked_250", "check": lambda s, c: s["likes_received"] + s["reply_likes_received"] >= 250},
    {"code": "late_start", "check": lambda s, c: s["tutorials_completed"] >= 1},
    {"code": "study_3", "check": lambda s, c: s["tutorials_completed"] >= 3},
    {"code": "graduate_all", "check": lambda s, c: s["tutorials_completed"] >= _learning_catalog_size("tutorial", 9)},
    {"code": "dict_10", "check": lambda s, c: s["terms_completed"] >= 10},
    {"code": "dict_all", "check": lambda s, c: s["terms_completed"] >= _learning_catalog_size("term", 26)},
]


def check_user_achievements(user: User) -> list[Achievement]:
    """Award every badge whose condition is met; idempotent; returns new grants."""
    stats = compute_user_stats(user)
    try:
        contribution = int(PointAccount.objects.get(user=user).contribution_score or 0)
    except PointAccount.DoesNotExist:
        contribution = 0
    owned = set(
        UserAchievement.objects.filter(user=user).values_list("achievement__code", flat=True)
    )
    by_code = {a.code: a for a in Achievement.objects.filter(is_active=True)}
    new_grants: list[Achievement] = []
    for rule in BADGE_RULES:
        achievement = by_code.get(rule["code"])
        if not achievement or achievement.code in owned:
            continue
        try:
            if not rule["check"](stats, contribution):
                continue
        except Exception:
            continue
        UserAchievement.objects.get_or_create(user=user, achievement=achievement, defaults={"granted_by": "system"})
        new_grants.append(achievement)
        from apps.notifications.services import notify

        notify(
            recipient=user, type_="badge",
            title=f"获得{ {"gold": "金牌", "silver": "银牌", "bronze": "铜牌"}.get(achievement.tier, "") }勋章「{achievement.name}」",
            body=achievement.description,
            link="/achievements",
        )
    if new_grants:
        promote_user_level(user, stats=stats)
    return new_grants


def grant_achievement(user: User, achievement: Achievement, *, granted_by: str) -> UserAchievement:
    grant, created = UserAchievement.objects.get_or_create(
        user=user, achievement=achievement, defaults={"granted_by": granted_by}
    )
    return grant


def achievement_payload(achievement: Achievement, *, holder_count: int | None = None, earned_at: str = "") -> dict:
    return {
        "code": achievement.code,
        "name": achievement.name,
        "description": achievement.description,
        "icon": achievement.icon,
        "tier": achievement.tier,
        "category": achievement.category,
        "holderCount": holder_count,
        "earnedAt": earned_at,
    }


def showcase_payload(user: User) -> dict | None:
    """用户选定展示的勋章（佩戴中）。"""
    try:
        stats = UserStats.objects.select_related("showcase").get(user=user)
        achievement = stats.showcase
        if achievement:
            return {"code": achievement.code, "name": achievement.name, "icon": achievement.icon, "tier": achievement.tier}
    except Exception:
        pass
    return None


def badges_payload(user: User) -> list[dict]:
    rows = (
        UserAchievement.objects.filter(user=user)
        .select_related("achievement")
        .order_by("-granted_at")
    )
    return [
        {
            "code": row.achievement.code,
            "name": row.achievement.name,
            "tier": row.achievement.tier,
            "icon": row.achievement.icon,
            "grantedAt": row.granted_at.isoformat(),
        }
        for row in rows
    ]
