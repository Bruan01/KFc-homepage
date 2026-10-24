# pyright: reportMissingImports=false
"""Feeds API views: public directory, AIHOT-backed timeline + hot topics."""
from __future__ import annotations

import time

from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.responses import json_ok

from .models import FeedFetchRun, FeedItem, FeedSource
from . import services

SOURCE_CATEGORY_ORDER = [code for code, _ in FeedSource.CATEGORY_CHOICES]
DEFAULT_LIMIT = 40
MAX_LIMIT = 100

# 热榜直接代理 AIHOT 并在进程内缓存 10 分钟，避免每次页面请求都打上游。
HOT_CACHE_TTL = 600
_hot_cache: dict[str, object] = {"at": 0.0, "items": []}


@require_GET
def feeds_sources(request):
    """Directory of curated sources; embeds latest fetch status per source."""
    latest_runs: dict[str, FeedFetchRun] = {}
    for run in FeedFetchRun.objects.filter(status__in=["success", "failed"]).order_by("-started_at"):
        if run.source_slug not in latest_runs:
            latest_runs[run.source_slug] = run
    sources = []
    for source in FeedSource.objects.filter(is_active=True):
        run = latest_runs.get(source.slug)
        sources.append(
            {
                "slug": source.slug,
                "name": source.name,
                "category": source.category,
                "category_label": source.get_category_display(),
                "site_url": source.site_url,
                "description": source.description,
                "language": source.language,
                "icon": source.icon,
                "has_feed": bool(source.feed_url),
                "last_fetched_at": source.last_fetched_at.isoformat() if source.last_fetched_at else None,
                "fetch_status": run.status if run else "",
            }
        )
    sources.sort(
        key=lambda s: (
            SOURCE_CATEGORY_ORDER.index(s["category"]) if s["category"] in SOURCE_CATEGORY_ORDER else 99,
            s["slug"],
        )
    )
    return json_ok(
        {
            "items": sources,
            "categories": [{"code": code, "label": label} for code, label in FeedSource.CATEGORY_CHOICES],
        }
    )


@require_GET
def feeds_items(request):
    """Aggregated timeline from AIHOT: metadata only, always links out."""
    source_slug = (request.GET.get("source") or "").strip()
    category = (request.GET.get("category") or "").strip()
    try:
        limit = min(MAX_LIMIT, max(1, int(request.GET.get("limit", DEFAULT_LIMIT))))
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        limit, offset = DEFAULT_LIMIT, 0

    category_labels = dict(FeedItem.CATEGORY_CHOICES)
    qs = FeedItem.objects.select_related("source").filter(source__is_active=True)
    if source_slug:
        qs = qs.filter(source__slug=source_slug)
    if category:
        qs = qs.filter(category=category)
    total = qs.count()
    items = [
        {
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "summary": item.summary,
            "published_at": item.published_at.isoformat(),
            "category": item.category,
            "category_label": category_labels.get(item.category, item.category),
            "score": item.score,
            "upstream_name": item.upstream_name,
            "via_name": item.via_name,
            "via_url": item.via_url,
            "source": {
                "slug": item.source.slug,
                "name": item.source.name,
                "icon": item.source.icon,
                "site_url": item.source.site_url,
            },
        }
        for item in qs[offset : offset + limit]
    ]
    return json_ok(
        {
            "items": items,
            "total": total,
            "has_more": offset + limit < total,
            "categories": [{"code": code, "label": label} for code, label in FeedItem.CATEGORY_CHOICES],
            "server_time": timezone.now().isoformat(),
        }
    )


@require_GET
def feeds_hot(request):
    """Proxy AIHOT hot topics with a process-local cache; falls back to empty."""
    now = time.monotonic()
    items = _hot_cache.get("items") or []
    if now - float(_hot_cache.get("at") or 0) > HOT_CACHE_TTL or not items:
        try:
            items = services.fetch_aihot_hot_topics()
            _hot_cache["at"] = now
            _hot_cache["items"] = items
        except Exception:
            if not items:
                _hot_cache["at"] = now  # 失败也记时间，避免每请求都打上游
    return json_ok({"items": items, "via": {"name": "AIHOT", "url": "https://aihot.news/"}})
