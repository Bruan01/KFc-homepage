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


STATS_FIELDS = (
    "active_days", "topics", "replies", "likes_given", "likes_received",
    "reply_likes_received", "votes_cast", "boosts_bought", "listings_sold",
    "max_topic_likes", "tutorials_completed", "terms_completed",
)


def _blank_stats() -> dict[str, int]:
    return {field: 0 for field in STATS_FIELDS}


def compute_users_stats(users: list[User]) -> dict[int, dict[str, int]]:
    """Batch version of :func:`compute_user_stats`.

    点赞这类会同时影响「点赞者 + 被赞作者」的操作，逐人统计会每人 13 次查询；
    这里改成按用户分组聚合，查询数与人数无关（约 12 次），单次请求即可覆盖
    多人的勋章判定。字段与返回结构与单用户版完全一致。
    """
    from apps.forum.models import ForumLike, ForumReply, ForumReplyLike, ForumTopic, TopicBoost
    from apps.rankings.models import ExternalProjectVote
    from apps.store.models import ListingRedemption

    ordered: list[User] = list({user.pk: user for user in users if user is not None}.values())
    if not ordered:
        return {}
    names = [user.username for user in ordered]
    by_name = {user.username: user.pk for user in ordered}
    stats = {user.pk: _blank_stats() for user in ordered}

    def _bump(rows, field: str) -> None:
        """rows: iterable of (username, count)。"""
        for name, count in rows:
            target = stats.get(by_name.get(name))
            if target is not None:
                target[field] += int(count or 0)

    def _bump_by_id(rows, field: str) -> None:
        for user_id, count in rows:
            target = stats.get(user_id)
            if target is not None:
                target[field] += int(count or 0)

    open_topics = ForumTopic.objects.filter(author_username__in=names, status=ForumTopic.STATUS_OPEN)
    _bump(
        open_topics.order_by().values("author_username").annotate(c=Count("id")).values_list("author_username", "c"),
        "topics",
    )
    _bump(
        ForumReply.objects.filter(
            author_username__in=names, is_deleted=False, topic__status=ForumTopic.STATUS_OPEN
        ).order_by().values("author_username").annotate(c=Count("id")).values_list("author_username", "c"),
        "replies",
    )
    # 单篇最高赞：先按 (作者, 主题) 聚合点赞数，再取每个作者的最大值
    per_topic_likes = (
        ForumLike.objects.filter(topic__status=ForumTopic.STATUS_OPEN, topic__author_username__in=names)
        .order_by().values("topic__author_username", "topic_id").annotate(c=Count("id"))
        .values_list("topic__author_username", "c")
    )
    max_likes: dict[str, int] = {}
    for name, count in per_topic_likes:
        if count > max_likes.get(name, 0):
            max_likes[name] = count
    _bump(max_likes.items(), "max_topic_likes")

    _bump(
        ForumLike.objects.filter(username__in=names).order_by().values("username").annotate(c=Count("id")).values_list("username", "c"),
        "likes_given",
    )
    _bump(
        ForumLike.objects.filter(topic__author_username__in=names).order_by()
        .values("topic__author_username").annotate(c=Count("id")).values_list("topic__author_username", "c"),
        "likes_received",
    )
    _bump(
        ForumReplyLike.objects.filter(username__in=names).order_by().values("username").annotate(c=Count("id")).values_list("username", "c"),
        "likes_given",
    )
    _bump(
        ForumReplyLike.objects.filter(reply__author_username__in=names).order_by()
        .values("reply__author_username").annotate(c=Count("id")).values_list("reply__author_username", "c"),
        "reply_likes_received",
    )
    _bump(
        ExternalProjectVote.objects.filter(username__in=names).order_by().values("username").annotate(c=Count("id")).values_list("username", "c"),
        "votes_cast",
    )
    _bump(
        TopicBoost.objects.filter(username__in=names).order_by().values("username").annotate(c=Count("id")).values_list("username", "c"),
        "boosts_bought",
    )
    _bump(
        ListingRedemption.objects.filter(seller_username__in=names).order_by()
        .values("seller_username").annotate(c=Count("id")).values_list("seller_username", "c"),
        "listings_sold",
    )

    # 活跃天数（按日期去重）
    for user_id, _date in (
        UserDailyActivity.objects.filter(user__in=ordered)
        .values_list("user_id", "activity_date").distinct()
    ):
        target = stats.get(user_id)
        if target is not None:
            target["active_days"] += 1

    try:
        from apps.learn.models import LearnProgress

        rows = LearnProgress.objects.filter(user__in=ordered).order_by().values("user_id", "kind").annotate(c=Count("id"))
        for row in rows:
            target = stats.get(row["user_id"])
            if target is None:
                continue
            if row["kind"] == "tutorial":
                target["tutorials_completed"] += int(row["c"] or 0)
            elif row["kind"] == "term":
                target["terms_completed"] += int(row["c"] or 0)
    except Exception:
        pass
    return stats


def refresh_user_stats_table(chunk_size: int = 200) -> int:
    """Bulk refresh the UserStats snapshot for all users with any activity.

    按批走 compute_users_stats：原来是每人 13 次查询，现在每批约 12 次。
    """
    updated = 0
    users = list(User.objects.all().order_by("id"))
    for start in range(0, len(users), chunk_size):
        chunk = users[start : start + chunk_size]
        stats_map = compute_users_stats(chunk)
        for user in chunk:
            UserStats.objects.update_or_create(user=user, defaults=stats_map.get(user.pk) or _blank_stats())
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
                title=f"等级提升：你已升级到 LV{new_level} {entry['name']}",
                body="；".join(entry.get("perks", []))[:280],
                link="/levels",
            )
    return new_level


def refresh_all_levels(chunk_size: int = 200) -> int:
    """重算所有人的等级（只升不降）。按批统计，避免每人 13 次查询。"""
    changed = 0
    accounts = list(PointAccount.objects.select_related("user").order_by("user_id"))
    for start in range(0, len(accounts), chunk_size):
        chunk = accounts[start : start + chunk_size]
        users = [account.user for account in chunk if account.user_id]
        stats_map = compute_users_stats(users)
        for account in chunk:
            user = account.user
            if not user:
                continue
            stats = stats_map.get(user.pk) or _blank_stats()
            old_level = int(account.reputation_level or 0)
            new_level = compute_level(stats, int(account.contribution_score or 0), old_level)
            if new_level == old_level:
                continue
            account.reputation_level = new_level
            account.save(update_fields=["reputation_level"])
            changed += 1
            if new_level > old_level:
                from apps.notifications.services import notify

                entry = level_config(new_level)
                notify(
                    recipient=user, type_="level",
                    title=f"等级提升：你已升级到 LV{new_level} {entry['name']}",
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
    # 创作
    {"code": "first_post",      "metric_key": "topics",            "threshold": 1,    "requirement": "发布 1 篇主题帖",                     "check": lambda s, c: s["topics"] >= 1},
    {"code": "author_3",        "metric_key": "topics",            "threshold": 3,    "requirement": "发布 3 篇主题帖",                      "check": lambda s, c: s["topics"] >= 3},
    {"code": "author_10",       "metric_key": "topics",            "threshold": 10,   "requirement": "发布 10 篇主题帖",                     "check": lambda s, c: s["topics"] >= 10},
    {"code": "notable_work",    "metric_key": "max_topic_likes",   "threshold": 10,   "requirement": "单篇主题帖累计获赞 ≥10",              "check": lambda s, c: s["max_topic_likes"] >= 10},
    {"code": "notable_work_25", "metric_key": "max_topic_likes",   "threshold": 25,   "requirement": "单篇主题帖累计获赞 ≥25",              "check": lambda s, c: s["max_topic_likes"] >= 25},
    {"code": "famous_work",     "metric_key": "max_topic_likes",   "threshold": 50,   "requirement": "单篇主题帖累计获赞 ≥50",              "check": lambda s, c: s["max_topic_likes"] >= 50},
    # 互动
    {"code": "first_reply",     "metric_key": "replies",          "threshold": 1,    "requirement": "回复 1 次",                             "check": lambda s, c: s["replies"] >= 1},
    {"code": "reply_10",       "metric_key": "replies",          "threshold": 10,   "requirement": "回复 10 次",                            "check": lambda s, c: s["replies"] >= 10},
    {"code": "helper_50",       "metric_key": "replies",          "threshold": 50,   "requirement": "回复 50 次",                            "check": lambda s, c: s["replies"] >= 50},
    {"code": "first_like",      "metric_key": "likes_given",      "threshold": 1,    "requirement": "点赞 1 次",                             "check": lambda s, c: s["likes_given"] >= 1},
    {"code": "likes_given_10",  "metric_key": "likes_given",      "threshold": 10,   "requirement": "点赞 10 次",                            "check": lambda s, c: s["likes_given"] >= 10},
    {"code": "liked_25",        "metric_key": "likes_total",      "threshold": 25,   "requirement": "主题 + 回复累计获赞 ≥25",              "check": lambda s, c: s["likes_received"] + s["reply_likes_received"] >= 25},
    {"code": "liked_100",       "metric_key": "likes_total",      "threshold": 100,  "requirement": "主题 + 回复累计获赞 ≥100",             "check": lambda s, c: s["likes_received"] + s["reply_likes_received"] >= 100},
    {"code": "liked_250",       "metric_key": "likes_total",      "threshold": 250,  "requirement": "主题 + 回复累计获赞 ≥250",             "check": lambda s, c: s["likes_received"] + s["reply_likes_received"] >= 250},
    {"code": "reply_likes_10",  "metric_key": "reply_likes_received", "threshold": 10, "requirement": "回复被点赞 ≥10",                       "check": lambda s, c: s["reply_likes_received"] >= 10},
    # 活跃
    {"code": "regular_3",      "metric_key": "active_days",      "threshold": 3,    "requirement": "活跃天数 ≥3",                          "check": lambda s, c: s["active_days"] >= 3},
    {"code": "active_7",       "metric_key": "active_days",      "threshold": 7,    "requirement": "活跃天数 ≥7",                          "check": lambda s, c: s["active_days"] >= 7},
    {"code": "veteran_14",      "metric_key": "active_days",      "threshold": 14,   "requirement": "活跃天数 ≥14",                         "check": lambda s, c: s["active_days"] >= 14},
    {"code": "active_30",      "metric_key": "active_days",      "threshold": 30,   "requirement": "活跃天数 ≥30",                         "check": lambda s, c: s["active_days"] >= 30},
    {"code": "ancient_100",    "metric_key": "active_days",      "threshold": 100,  "requirement": "活跃天数 ≥100",                        "check": lambda s, c: s["active_days"] >= 100},
    # 学习
    {"code": "late_start",     "metric_key": "tutorials_completed", "threshold": 1,  "requirement": "完成 1 个教程",                        "check": lambda s, c: s["tutorials_completed"] >= 1},
    {"code": "study_3",        "metric_key": "tutorials_completed", "threshold": 3,  "requirement": "完成 3 个教程",                        "check": lambda s, c: s["tutorials_completed"] >= 3},
    {"code": "study_6",        "metric_key": "tutorials_completed", "threshold": 6,  "requirement": "完成 6 个教程",                        "check": lambda s, c: s["tutorials_completed"] >= 6},
    {"code": "graduate_all",   "metric_key": "tutorials_completed", "threshold": 9,  "requirement": "完成全部教程",                        "check": lambda s, c: s["tutorials_completed"] >= _learning_catalog_size("tutorial", 9)},
    {"code": "dict_5",         "metric_key": "terms_completed",  "threshold": 5,    "requirement": "掌握 5 个术语",                        "check": lambda s, c: s["terms_completed"] >= 5},
    {"code": "dict_10",        "metric_key": "terms_completed",  "threshold": 10,   "requirement": "掌握 10 个术语",                       "check": lambda s, c: s["terms_completed"] >= 10},
    {"code": "dict_all",       "metric_key": "terms_completed",  "threshold": 26,   "requirement": "掌握全部术语",                       "check": lambda s, c: s["terms_completed"] >= _learning_catalog_size("term", 26)},
    # 商务
    {"code": "first_boost",    "metric_key": "boosts_bought",    "threshold": 1,    "requirement": "购买 1 次加热",                        "check": lambda s, c: s["boosts_bought"] >= 1},
    {"code": "boost_3",        "metric_key": "boosts_bought",    "threshold": 3,    "requirement": "购买 3 次加热",                        "check": lambda s, c: s["boosts_bought"] >= 3},
    {"code": "boost_10",       "metric_key": "boosts_bought",    "threshold": 10,   "requirement": "购买 10 次加热",                       "check": lambda s, c: s["boosts_bought"] >= 10},
    {"code": "first_vote",     "metric_key": "votes_cast",       "threshold": 1,    "requirement": "投出 1 票(创意赞)",                  "check": lambda s, c: s["votes_cast"] >= 1},
    {"code": "vote_10",        "metric_key": "votes_cast",       "threshold": 10,   "requirement": "投出 10 票",                           "check": lambda s, c: s["votes_cast"] >= 10},
    {"code": "voter_50",       "metric_key": "votes_cast",       "threshold": 50,   "requirement": "投出 50 票",                           "check": lambda s, c: s["votes_cast"] >= 50},
    {"code": "seller_first",   "metric_key": "listings_sold",    "threshold": 1,    "requirement": "售出 1 件 kflowstore 商品",            "check": lambda s, c: s["listings_sold"] >= 1},
    {"code": "seller_5",       "metric_key": "listings_sold",    "threshold": 5,    "requirement": "售出 5 件 kflowstore 商品",            "check": lambda s, c: s["listings_sold"] >= 5},
    # 贡献分
    {"code": "pillar_500",     "metric_key": "contribution",     "threshold": 500,  "requirement": "社区贡献分 ≥500",                     "check": lambda s, c: c >= 500},
    {"code": "contributor_1000","metric_key": "contribution",    "threshold": 1000, "requirement": "社区贡献分 ≥1000",                    "check": lambda s, c: c >= 1000},
]

# 进度条上把 metric_key 翻译成中文标签
_METRIC_LABEL: dict[str, str] = {
    "topics": "主题帖",
    "replies": "回复",
    "likes_given": "送出点赞",
    "likes_received": "主题获赞",
    "reply_likes_received": "回复获赞",
    "likes_total": "累计获赞",
    "active_days": "活跃天数",
    "max_topic_likes": "单篇最高赞",
    "tutorials_completed": "完成教程",
    "terms_completed": "掌握术语",
    "boosts_bought": "购买加热",
    "votes_cast": "投出票数",
    "listings_sold": "售出商品",
    "contribution": "贡献分",
}

# 字段名 → 用户 stat dict 真实键名 的映射(部分 key 是合并字段)
_METRIC_SOURCE: dict[str, str] = {
    "topics": "topics",
    "replies": "replies",
    "likes_given": "likes_given",
    "likes_received": "likes_received",
    "reply_likes_received": "reply_likes_received",
    "likes_total": "__likes_total",  # 需要现算
    "active_days": "active_days",
    "max_topic_likes": "max_topic_likes",
    "tutorials_completed": "tutorials_completed",
    "terms_completed": "terms_completed",
    "boosts_bought": "boosts_bought",
    "votes_cast": "votes_cast",
    "listings_sold": "listings_sold",
    "contribution": "__contribution",  # 单独存
}


def _resolve_metric(metric_key: str, stats: dict, contribution: int) -> int:
    src = _METRIC_SOURCE.get(metric_key)
    if src == "__likes_total":
        return int(stats.get("likes_received", 0)) + int(stats.get("reply_likes_received", 0))
    if src == "__contribution":
        return int(contribution)
    return int(stats.get(src, 0)) if src else 0


def rule_for(code: str) -> dict | None:
    for r in BADGE_RULES:
        if r["code"] == code:
            return r
    return None


def check_users_achievements(users: list[User]) -> dict[str, list[Achievement]]:
    """Batch badge check: 返回 {username: [新授予的勋章]}。

    勋章规则与等级逻辑与单用户版完全一致，但统计一次性批量完成，
    查询数与人数无关：点赞这类「同时影响点赞者和作者」的操作用它只跑一轮统计。
    """
    ordered: list[User] = list({user.pk: user for user in users if user is not None}.values())
    if not ordered:
        return {}
    stats_map = compute_users_stats(ordered)
    contributions = {
        account.user_id: int(account.contribution_score or 0)
        for account in PointAccount.objects.filter(user__in=ordered)
    }
    owned: dict[int, set[str]] = {}
    for user_id, code in (
        UserAchievement.objects.filter(user__in=ordered).values_list("user_id", "achievement__code")
    ):
        owned.setdefault(user_id, set()).add(code)
    by_code = {a.code: a for a in Achievement.objects.filter(is_active=True)}

    grants: dict[str, list[Achievement]] = {}
    for user in ordered:
        stats = stats_map.get(user.pk) or _blank_stats()
        user_owned = owned.setdefault(user.pk, set())
        contribution = contributions.get(user.pk, 0)
        new_grants: list[Achievement] = []
        for rule in BADGE_RULES:
            achievement = by_code.get(rule["code"])
            if not achievement or achievement.code in user_owned:
                continue
            try:
                if not rule["check"](stats, contribution):
                    continue
            except Exception:
                continue
            UserAchievement.objects.get_or_create(user=user, achievement=achievement, defaults={"granted_by": "system"})
            user_owned.add(achievement.code)
            new_grants.append(achievement)
            from apps.notifications.services import notify

            notify(
                recipient=user, type_="badge",
                title=f"获得{ {'gold': '金牌', 'silver': '银牌', 'bronze': '铜牌'}.get(achievement.tier, '') }勋章「{achievement.name}」",
                body=achievement.description,
                link="/achievements",
            )
        if new_grants:
            promote_user_level(user, stats=stats)
            grants[user.username] = new_grants
    return grants


def check_user_achievements(user: User) -> list[Achievement]:
    """Award every badge whose condition is met; idempotent; returns new grants."""
    return check_users_achievements([user]).get(user.username, [])


def grant_achievement(user: User, achievement: Achievement, *, granted_by: str) -> UserAchievement:
    grant, created = UserAchievement.objects.get_or_create(
        user=user, achievement=achievement, defaults={"granted_by": granted_by}
    )
    return grant


def achievement_payload(
    achievement: Achievement,
    *,
    holder_count: int | None = None,
    earned_at: str = "",
    user_stats: dict | None = None,
    user_contribution: int | None = None,
) -> dict:
    rule = rule_for(achievement.code)
    payload = {
        "code": achievement.code,
        "name": achievement.name,
        "description": achievement.description,
        "icon": achievement.icon,
        "tier": achievement.tier,
        "category": achievement.category,
        "holderCount": holder_count,
        "earnedAt": earned_at,
        "requirement": (rule or {}).get("requirement", achievement.description or ""),
        "metricKey": (rule or {}).get("metric_key", ""),
        "threshold": (rule or {}).get("threshold", 0),
    }
    if user_stats is not None:
        metric_key = payload["metricKey"]
        current = (
            _resolve_metric(metric_key, user_stats, user_contribution or 0)
            if metric_key else 0
        )
        threshold = payload["threshold"]
        payload["currentValue"] = current
        payload["progress"] = min(current, threshold) if threshold else current
        payload["done"] = bool(threshold and current >= threshold)
    return payload


def showcases_payload(usernames) -> dict[str, dict]:
    """Batch public worn badges for author cards, with no per-author queries."""
    names = set(usernames)
    if not names:
        return {}
    rows = UserStats.objects.filter(user__username__in=names, showcase__isnull=False).values(
        "user__username", "showcase__code", "showcase__name", "showcase__icon", "showcase__tier",
    )
    return {
        row["user__username"]: {
            field: row[f"showcase__{field}"] for field in ("code", "name", "icon", "tier")
        }
        for row in rows
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
