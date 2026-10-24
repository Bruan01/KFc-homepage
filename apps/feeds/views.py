# pyright: reportMissingImports=false
"""Feeds API views: public directory, AIHOT-backed timeline + hot topics."""
from __future__ import annotations

import time
from datetime import timedelta

from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.http import read_json
from apps.core.permissions import get_admin_context
from apps.core.responses import json_error, json_ok

from .models import FeedFetchRun, FeedItem, FeedSource
from . import services

SOURCE_CATEGORY_ORDER = [code for code, _ in FeedSource.CATEGORY_CHOICES]
DEFAULT_LIMIT = 40
MAX_LIMIT = 100

# 热榜直接代理 AIHOT 并在进程内缓存 10 分钟，避免每次页面请求都打上游。
HOT_CACHE_TTL = 600
_hot_cache: dict[str, object] = {"at": 0.0, "items": []}

# 问小K：每用户每小时最多 10 次（进程内计数，重启清零）。
ASK_HOURLY_LIMIT = 10
ASK_CONTEXT_HOURS = 48
ASK_CONTEXT_ITEMS = 15
_ask_counters: dict[str, list] = {}


@require_GET
def feeds_sources(request):
    """Directory of curated sources; embeds latest fetch status per source."""
    latest_runs: dict[str, FeedFetchRun] = {}
    for run in FeedFetchRun.objects.filter(status__in=["success", "failed"]).order_by("-started_at"):
        if run.source_slug not in latest_runs:
            latest_runs[run.source_slug] = run
    # 新鲜度：最近一次成功抓取距今超过 2 小时即视为停更（服务器时钟判定）。
    latest_success = FeedFetchRun.objects.filter(status="success").order_by("-finished_at").first()
    last_success_at = latest_success.finished_at if latest_success else None
    stale_after = timedelta(hours=2)
    freshness = {
        "last_success_at": last_success_at.isoformat() if last_success_at else None,
        "is_stale": last_success_at is None or (timezone.now() - last_success_at) > stale_after,
    }
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
            "freshness": freshness,
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


def _actor(request) -> str:
    admin = get_admin_context(request)
    if admin:
        return admin["username"]
    return request.user.username if request.user.is_authenticated else ""


def _ask_allowed(username: str) -> bool:
    now = time.monotonic()
    window_start, count = _ask_counters.get(username, (now, 0))
    if now - window_start > 3600:
        window_start, count = now, 0
    count += 1
    _ask_counters[username] = (window_start, count)
    return count <= ASK_HOURLY_LIMIT


@require_POST
def feeds_ask(request):
    """问小K：基于近期 AI 资讯的对话式摄入，回答带【n】引用。"""
    username = _actor(request)
    if not username:
        return json_error("登录后就可以问小K", status=401)
    if not _ask_allowed(username):
        return json_error("问得太快啦，休息一下再问～（每小时 10 次）", status=429)

    try:
        body = read_json(request)
    except Exception:
        return json_error("请求格式无效")
    question = str((body or {}).get("question", "")).strip()[:300]
    if len(question) < 2:
        return json_error("想问小K 点什么？")

    from apps.community_ai.models import AssistantSettings
    from apps.community_ai.provider import ProviderError, complete

    config = AssistantSettings.objects.filter(pk=1, enabled=True).first()
    if not config or not config.base_url or not config.model:
        return json_error("小K 的对话服务暂未开通，管理员可在后台「小K 官方助手」配置", status=503)

    since = timezone.now() - timedelta(hours=ASK_CONTEXT_HOURS)
    items = list(FeedItem.objects.filter(published_at__gte=since).order_by("-score", "-published_at")[:ASK_CONTEXT_ITEMS])
    if not items:
        items = list(FeedItem.objects.order_by("-published_at")[:ASK_CONTEXT_ITEMS])
    if not items:
        return json_error("资讯库还是空的，稍后再来问小K", status=503)

    category_labels = dict(FeedItem.CATEGORY_CHOICES)
    refs = [
        {
            "n": idx + 1,
            "title": item.title,
            "url": item.url,
            "source": item.upstream_name or item.source.name,
            "score": item.score,
            "category_label": category_labels.get(item.category, ""),
        }
        for idx, item in enumerate(items)
    ]
    context_lines = [
        f"【{idx + 1}】{item.score}分 [{category_labels.get(item.category, '')}] {item.title} —— {item.summary}（来源：{item.upstream_name or item.source.name}）"
        for idx, item in enumerate(items)
    ]
    instruction = (
        "你是 KFlow 社区的 AI 助手小K，正在「AI 电讯」页值班编辑。请只依据下面的资讯资料回答用户问题，"
        "不要编造资讯。回答用简体中文，默认 120 字以内（用户明确要求展开时可更长），口语化、有编辑观点。"
        "引用某条资讯时必须在句末标注【编号】，例如【3】；可以组合多条。若资料不足以回答，直接说明并建议去 /feeds 翻时间流。"
    )
    messages = [
        {"role": "system", "content": f"{instruction}\n\n角色设定：\n{config.persona}"},
        {"role": "user", "content": f"{question}\n\n资讯资料（最近48小时按评分排序）：\n" + "\n".join(context_lines)},
    ]
    try:
        answer = complete(config, messages)
    except ProviderError as exc:
        return json_error(str(exc), status=503)
    return json_ok({"answer": answer, "refs": refs})
