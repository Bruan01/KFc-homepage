# pyright: reportMissingImports=false
"""Gamification API: achievements, levels, contribution stats, admin."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User
from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import get_admin_context, require_admin
from apps.core.responses import json_error, json_ok
from apps.forum.models import ForumLike, ForumReply, ForumReplyLike, ForumTopic
from apps.points.models import PointAccount

from .models import Achievement, UserAchievement, UserStats
from .services import (
    LEVELS,
    achievement_payload,
    badges_payload,
    compute_level,
    compute_user_stats,
    grant_achievement,
    level_config,
)

TIER_ORDER = {"gold": 0, "silver": 1, "bronze": 2}


def _actor(request) -> str:
    admin = get_admin_context(request)
    if admin:
        return admin["username"]
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user.username
    return ""


@require_GET
def achievements(request):
    username = _actor(request)
    earned_map: dict[str, str] = {}
    if username:
        try:
            user = User.objects.get(username=username)
            earned_map = dict(
                UserAchievement.objects.filter(user=user)
                .values_list("achievement__code", "granted_at")
            )
            earned_map = {k: v.isoformat() for k, v in earned_map.items()}
        except User.DoesNotExist:
            pass
    counts = {
        row["achievement__code"]: row["cnt"]
        for row in UserAchievement.objects.values("achievement__code").annotate(cnt=Count("id"))
    }
    items = []
    for achievement in Achievement.objects.filter(is_active=True):
        payload = achievement_payload(
            achievement,
            holder_count=counts.get(achievement.code, 0),
            earned_at=earned_map.get(achievement.code, ""),
        )
        items.append(payload)
    items.sort(key=lambda a: (TIER_ORDER.get(a["tier"], 3), a["code"]))
    my_badges = badges_payload(User.objects.get(username=username)) if username else []
    return json_ok({
        "items": items,
        "mine": my_badges,
        "total": len(items),
        "earned": len(my_badges),
    })


@require_GET
def levels(request):
    username = _actor(request)
    context: dict = {"levels": LEVELS, "my": None}
    if username:
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return json_ok(context)
        stats = compute_user_stats(user)
        try:
            account = PointAccount.objects.get(user=user)
            contribution = int(account.contribution_score or 0)
            current = int(account.reputation_level or 0)
        except PointAccount.DoesNotExist:
            contribution, current = 0, 0
        # 距下一级进度
        progress = None
        next_entry = next((e for e in LEVELS if e["level"] == current + 1), None)
        if next_entry and next_entry["requirements"]:
            metrics = {**stats, "contribution": contribution}
            parts = []
            for key, threshold in next_entry["requirements"].items():
                value = metrics.get(key, 0)
                parts.append({"key": key, "value": value, "threshold": threshold, "done": value >= threshold})
            progress = {"nextLevel": next_entry["level"], "nextName": next_entry["name"], "parts": parts,
                        "complete": all(p["done"] for p in parts)}
        context["my"] = {
            "level": current,
            "name": level_config(current)["name"],
            "contribution": contribution,
            "stats": stats,
            "progress": progress,
        }
    return json_ok(context)


@require_GET
def stats_overview(request):
    days = request.GET.get("days", "").strip()
    since = None
    if days.isdigit() and int(days) > 0:
        since = timezone.now() - timedelta(days=int(days))
    topic_q = Q(status=ForumTopic.STATUS_OPEN)
    if since:
        topic_q &= Q(created_at__gte=since)
    reply_q = Q(is_deleted=False)
    if since:
        reply_q &= Q(created_at__gte=since)
    like_q = Q()
    if since:
        like_q &= Q(created_at__gte=since)
    from apps.gamification.models import UserAchievement

    return json_ok({
        "members": User.objects.count(),
        "topics": ForumTopic.objects.filter(topic_q).count(),
        "replies": ForumReply.objects.filter(reply_q).count(),
        "likes": ForumLike.objects.filter(like_q).count() + ForumReplyLike.objects.filter(like_q).count(),
        "badgesGranted": UserAchievement.objects.count(),
    })


@require_GET
def stats_contributors(request):
    """Contribution leaderboard with per-dimension breakdown."""
    period = request.GET.get("period", "all")
    if period not in {"weekly", "monthly", "all"}:
        period = "all"
    try:
        limit = min(50, max(1, int(request.GET.get("limit", 20))))
    except ValueError:
        limit = 20
    since = None
    if period == "weekly":
        since = timezone.now() - timedelta(days=7)
    elif period == "monthly":
        since = timezone.now() - timedelta(days=30)

    topic_q = Q(status=ForumTopic.STATUS_OPEN)
    reply_q = Q(is_deleted=False)
    if since:
        topic_q &= Q(created_at__gte=since)
        reply_q &= Q(created_at__gte=since)

    topics = (
        ForumTopic.objects.filter(topic_q)
        .values("author_username")
        .annotate(cnt=Count("id"))
    )
    replies = (
        ForumReply.objects.filter(reply_q)
        .values("author_username")
        .annotate(cnt=Count("id"))
    )
    likes_map: dict[str, int] = {}
    for row in ForumLike.objects.values("topic__author_username").annotate(cnt=Count("id")):
        likes_map[row["topic__author_username"]] = row["cnt"]
    for row in ForumReplyLike.objects.values("reply__author_username").annotate(cnt=Count("id")):
        likes_map[row["reply__author_username"]] = likes_map.get(row["reply__author_username"], 0) + row["cnt"]

    totals: dict[str, dict] = {}
    for row in topics:
        totals.setdefault(row["author_username"], {"topics": 0, "replies": 0, "likes": 0})["topics"] = row["cnt"]
    for row in replies:
        totals.setdefault(row["author_username"], {"topics": 0, "replies": 0, "likes": 0})["replies"] = row["cnt"]
    for name, cnt in likes_map.items():
        if name in totals:
            totals[name]["likes"] = cnt

    if not totals:
        return json_ok({"period": period, "items": []})

    names = list(totals.keys())
    users = {u.username: u for u in User.objects.filter(username__in=names)}
    accounts = {a.user.username: a for a in PointAccount.objects.select_related("user").filter(user__username__in=names)}
    badge_counts = {
        row["user__username"]: row["cnt"]
        for row in UserAchievement.objects.values("user__username").annotate(cnt=Count("id"))
    }

    items = []
    for name, agg in totals.items():
        user = users.get(name)
        account = accounts.get(name)
        score = (
            agg["topics"] * 10 + agg["replies"] * 2 + agg["likes"] * 1
            + int(account.contribution_score or 0) if account else agg["topics"] * 10 + agg["replies"] * 2 + agg["likes"]
        )
        display = (getattr(user, "display_name", "") or "").strip() or name
        items.append({
            "username": name,
            "displayName": display,
            "avatarUrl": getattr(user, "avatar_url", "") or "",
            "topics": agg["topics"],
            "replies": agg["replies"],
            "likes": agg["likes"],
            "contribution": int(account.contribution_score or 0) if account else 0,
            "level": int(account.reputation_level or 0) if account else 0,
            "badges": badge_counts.get(name, 0),
            "score": int(score),
        })
    items.sort(key=lambda x: -x["score"])
    for index, item in enumerate(items[:limit], start=1):
        item["rank"] = index
    return json_ok({"period": period, "items": items[:limit]})


# ── 管理端 ──────────────────────────────────────────────────────────────────


@require_admin(level=3)
@require_GET
def admin_overview(request):
    distribution = [
        {"level": entry["level"], "name": entry["name"], "count": count}
        for entry in LEVELS
        for count in [PointAccount.objects.filter(reputation_level=entry["level"]).count()]
    ]
    recent = (
        UserAchievement.objects.select_related("user", "achievement")
        .order_by("-granted_at")[:30]
    )
    return json_ok({
        "levelDistribution": distribution,
        "badgeTotal": Achievement.objects.filter(is_active=True).count(),
        "grantsTotal": UserAchievement.objects.count(),
        "recent": [
            {
                "username": row.user.username,
                "badge": row.achievement.name,
                "code": row.achievement.code,
                "grantedBy": row.granted_by,
                "grantedAt": row.granted_at.isoformat(),
            }
            for row in recent
        ],
    })


@require_admin(level=3)
@require_POST
def admin_grant(request):
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("invalid json")
    username = str(body.get("username", "")).strip()
    code = str(body.get("code", "")).strip()
    achievement = Achievement.objects.filter(code=code, is_active=True).first()
    if not achievement:
        return json_error("勋章不存在", status=404)
    user = User.objects.filter(username=username).first()
    if not user:
        return json_error("用户不存在", status=404)
    grant_achievement(user, achievement, granted_by=request.kflow_admin["username"])
    if code == "core_member":
        PointAccount.objects.update_or_create(
            user=user, defaults={"reputation_level": 4, "updated_at": timezone.now().isoformat()}
        )
    return json_ok({"ok": True})


@require_admin(level=3)
@require_POST
def admin_revoke(request):
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("invalid json")
    username = str(body.get("username", "")).strip()
    code = str(body.get("code", "")).strip()
    deleted, _ = UserAchievement.objects.filter(
        user__username=username, achievement__code=code
    ).delete()
    if not deleted:
        return json_error("该用户没有此勋章", status=404)
    return json_ok({"ok": True})


@require_admin(level=3)
@require_POST
def admin_recompute(request):
    from .services import refresh_user_stats_table, refresh_all_levels

    stats_count = refresh_user_stats_table()
    changed = refresh_all_levels()
    return json_ok({"ok": True, "statsRefreshed": stats_count, "levelsChanged": changed})
