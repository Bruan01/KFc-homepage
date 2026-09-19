# pyright: reportMissingImports=false
"""Rankings API views: site hot board, creator board, external board."""
from __future__ import annotations

import json
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User
from apps.core.permissions import get_admin_context
from apps.core.responses import json_error, json_ok
from apps.forum.models import ForumImage, ForumTopic
from apps.forum.services import parse_image_ids
from apps.points.models import PointAccount

from .models import CrawlRun, ExternalProject, ExternalProjectVote

PERIOD_DAYS = {"daily": 1, "weekly": 7, "all": 3650}
SOURCE_LABELS = {"kaiyuanbang": "开源榜"}


def _actor_username(request) -> str:
    admin = get_admin_context(request)
    if admin:
        return admin["username"]
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user.username
    return ""


def _topic_cover(topic: ForumTopic) -> str:
    ids = parse_image_ids(topic.images)
    return f"/api/forum/images/{ids[0]}" if ids else ""


@require_GET
def site_rankings(request):
    period = request.GET.get("period", "weekly")
    if period not in PERIOD_DAYS:
        period = "weekly"
    try:
        limit = min(100, max(1, int(request.GET.get("limit", 20))))
    except ValueError:
        limit = 20
    since = timezone.now() - timedelta(days=PERIOD_DAYS[period])
    qs = (
        ForumTopic.objects.filter(status=ForumTopic.STATUS_OPEN, created_at__gte=since)
        .select_related("category")
        .order_by("-hot_score", "-created_at")[:limit]
    )
    like_counts = {
        row["id"]: row["cnt"]
        for row in ForumTopic.objects.filter(id__in=[t.pk for t in qs]).values("id").annotate(cnt=Count("likes"))
    }
    items = []
    for topic in qs:
        items.append({
            "rank": len(items) + 1,
            "id": topic.pk,
            "title": topic.title,
            "author": topic.author_username,
            "category": topic.category.name,
            "category_color": topic.category.color,
            "likes": like_counts.get(topic.pk, 0),
            "replies": topic.reply_count,
            "views": max(topic.views, topic.dedup_views),
            "hot_score": round(topic.hot_score, 1),
            "cover": _topic_cover(topic),
            "created_at": topic.created_at.isoformat(),
        })
    return json_ok({"period": period, "items": items})


@require_GET
def creator_rankings(request):
    try:
        limit = min(100, max(1, int(request.GET.get("limit", 20))))
    except ValueError:
        limit = 20
    rows = list(
        PointAccount.objects.select_related("user")
        .filter(status="active", contribution_score__gt=0)
        .order_by("-contribution_score")[:limit]
    )
    topic_counts = {
        row["author_username"]: row["cnt"]
        for row in ForumTopic.objects.filter(status=ForumTopic.STATUS_OPEN)
        .values("author_username").annotate(cnt=Count("id"))
    }
    from apps.gamification.models import UserAchievement
    badge_counts = {
        row["user__username"]: row["cnt"]
        for row in UserAchievement.objects.values("user__username").annotate(cnt=Count("id"))
    }
    items = []
    for account in rows:
        user = account.user
        display_name = (getattr(user, "display_name", "") or "").strip() or user.username
        items.append({
            "rank": len(items) + 1,
            "username": user.username,
            "display_name": display_name,
            "avatar_url": getattr(user, "avatar_url", "") or "",
            "contribution_score": int(account.contribution_score or 0),
            "reputation_level": int(account.reputation_level or 0),
            "topic_count": topic_counts.get(user.username, 0),
            "badges": badge_counts.get(user.username, 0),
        })
    return json_ok({"items": items})


def _project_tags(project: ExternalProject) -> list:
    try:
        return json.loads(project.tags) if project.tags else []
    except (ValueError, TypeError):
        return []


def _project_payload(project: ExternalProject, *, voted: bool = False) -> dict:
    try:
        metrics = json.loads(project.metrics) if project.metrics else {}
    except (ValueError, TypeError):
        metrics = {}
    return {
        "id": project.pk,
        "source": project.source,
        "title": project.title,
        "description": project.description,
        "url": project.url,
        "author": project.author,
        "language": project.language or (metrics.get("language") or ""),
        # kaiyuanbang-style fields, mirrored from metrics for easier rendering
        "topic": metrics.get("topic") or "",
        "stars": int(metrics.get("stars") or 0),
        "forks": int(metrics.get("forks") or 0),
        "watching": int(metrics.get("watching") or metrics.get("watchers") or 0),
        "issues": int(metrics.get("issues") or metrics.get("open_issues") or 0),
        "homepage": metrics.get("homepage") or "",
        "license": metrics.get("license") or "",
        "growth_24h": int(metrics.get("growth_24h") or 0),
        "growth_7d": int(metrics.get("growth_7d") or 0),
        "growth_30d": int(metrics.get("growth_30d") or 0),
        "created_at": metrics.get("created_at") or "",
        "pushed_at_fact": metrics.get("pushed_at_fact") or "",
        "synced_at": metrics.get("synced_at") or "",
        "snapshots": metrics.get("snapshots") or [],
        "rank_position": int(metrics.get("rank") or 0),
        "metrics": metrics,
        "heat_score": round(project.heat_score, 1),
        "votes": project.votes,
        "voted": voted,
        "tags": _project_tags(project),
        "analyzed": bool(project.analyzed_at),
        "trend": project.trend_state or "fresh",
        "pushed_at": project.pushed_at.isoformat() if project.pushed_at else "",
        "last_crawled_at": project.last_crawled_at.isoformat(),
    }


@require_GET
def external_project_detail(request, project_id: int):
    """热榜项目详情：概括、标签、原文链接、设计剖析、趋势与预测、相关项目。"""
    from .analysis import TREND_LABEL, project_trend

    project = ExternalProject.objects.filter(pk=project_id, is_active=True).first()
    if not project:
        return json_error("项目不存在", status=404)
    try:
        metrics = json.loads(project.metrics) if project.metrics else {}
    except (ValueError, TypeError):
        metrics = {}
    try:
        analysis = json.loads(project.analysis) if project.analysis else {}
    except (ValueError, TypeError):
        analysis = {}
    try:
        tags = json.loads(project.tags) if project.tags else []
    except (ValueError, TypeError):
        tags = []
    trend = project_trend(project)

    # 相关项目：共享标签的其他在榜项目（最多 5 个）
    related = []
    if tags:
        candidates = ExternalProject.objects.filter(is_active=True).exclude(pk=project.pk)[:80]
        scored = []
        for candidate in candidates:
            try:
                candidate_tags = set(json.loads(candidate.tags) if candidate.tags else [])
            except (ValueError, TypeError):
                continue
            overlap = len(candidate_tags & set(tags))
            if overlap:
                scored.append((overlap, candidate.heat_score, candidate))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        related = [
            {"id": c.pk, "title": c.title, "url": c.url, "source": c.source,
             "heat": round(c.heat_score, 1), "sharedTags": overlap}
            for overlap, _heat, c in scored[:5]
        ]

    detail = {
        **_project_payload(project),
        "summary": project.summary or project.description[:120],
        "analysis": analysis,
        "analysisSource": project.analysis_source,
        "analyzedAt": project.analyzed_at.isoformat() if project.analyzed_at else "",
        "trend": trend,
        "trendLabel": trend.get("stateLabel") or TREND_LABEL.get(trend.get("state", ""), ""),
        "related": related,
        "sourceLabel": SOURCE_LABELS.get(project.source, project.source),
    }
    return json_ok({"project": detail})


@require_GET
def external_trends(request):
    """标签热点趋势与预测。"""
    from .analysis import tag_trends

    try:
        days = min(30, max(3, int(request.GET.get("days", 7))))
    except ValueError:
        days = 7
    return json_ok(tag_trends(days=days))


@require_GET
def external_rankings(request):
    source = request.GET.get("source", "").strip()
    period = request.GET.get("period", "all")
    try:
        limit = min(100, max(1, int(request.GET.get("limit", 30))))
    except ValueError:
        limit = 30
    username = _actor_username(request)
    qs = ExternalProject.objects.filter(is_active=True)
    if source and source != "all":
        qs = qs.filter(source=source)
    if period in PERIOD_DAYS and period != "all":
        since = timezone.now() - timedelta(days=PERIOD_DAYS[period])
        qs = qs.filter(pushed_at__gte=since)
    rows = list(qs.order_by("-heat_score", "-votes")[:limit])
    voted_ids: set[int] = set()
    if username and rows:
        voted_ids = set(
            ExternalProjectVote.objects.filter(project_id__in=[p.pk for p in rows], username=username)
            .values_list("project_id", flat=True)
        )
    items = [_project_payload(p, voted=p.pk in voted_ids) for p in rows]
    last_run = (
        ExternalProject.objects.filter(is_active=True)
        .order_by("-last_crawled_at")
        .values_list("last_crawled_at", flat=True)
        .first()
    )
    # per-source crawl status so the UI can explain empty boards
    latest_runs: dict[str, CrawlRun] = {}
    for crawl_run in CrawlRun.objects.order_by("-started_at")[:30]:
        latest_runs.setdefault(crawl_run.source, crawl_run)
    sources_status = []
    for source in ("kaiyuanbang",):
        run = latest_runs.get(source)
        sources_status.append({
            "source": source,
            "status": run.status if run else "never",
            "count": run.item_count if run else 0,
            "message": (run.message or "") if run else "",
            "finished_at": run.finished_at.isoformat() if (run and run.finished_at) else "",
        })
    return json_ok({
        "items": items,
        "updated_at": last_run.isoformat() if last_run else "",
        "sources": sources_status,
    })


@require_POST
def vote_external_project(request, project_id: int):
    username = _actor_username(request)
    if not username:
        return json_error("请先登录后再投票", status=401)
    project = ExternalProject.objects.filter(pk=project_id, is_active=True).first()
    if not project:
        return json_error("项目不存在", status=404)
    _, created = ExternalProjectVote.objects.get_or_create(project=project, username=username)
    if created:
        ExternalProject.objects.filter(pk=project.pk).update(votes=project.votes + 1)
        project.refresh_from_db(fields=["votes"])
    new_badges = []
    try:
        from apps.accounts.models import User
        from apps.gamification.services import check_user_achievements

        user_obj = User.objects.filter(username=username).first()
        if user_obj:
            new_badges = [b.name for b in check_user_achievements(user_obj)]
    except Exception:
        new_badges = []
    return json_ok({
        "votes": project.votes, "voted": True,
        "newBadges": [{"name": b.name, "icon": b.icon, "tier": b.tier} for b in new_badges],
    })
