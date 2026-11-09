# pyright: reportMissingImports=false
"""Feeds API views: public directory, AIHOT-backed timeline + hot topics."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.http import client_ip, read_json
from apps.core.permissions import get_admin_context
from apps.core.responses import json_error, json_ok

from .models import FeedAskQuota, FeedFetchRun, FeedItem, FeedSource
from . import services

SOURCE_CATEGORY_ORDER = [code for code, _ in FeedSource.CATEGORY_CHOICES]
DEFAULT_LIMIT = 40
MAX_LIMIT = 100

# 热榜直接代理 AIHOT 并在进程内缓存 10 分钟，避免每次页面请求都打上游。
HOT_CACHE_TTL = 600
_hot_cache: dict[str, object] = {"at": 0.0, "items": []}

# 问小K：游客按自然日 3 次、登录用户按自然小时 10 次，配额落库跨进程共享。
ASK_USER_HOURLY_LIMIT = 10
ASK_ANON_DAILY_LIMIT = 3
# 同 IP 游客总量兜底：防止清 cookie 反复刷收费模型。阈值留宽，避免 NAT 误伤。
ASK_ANON_IP_DAILY_LIMIT = 24
ASK_CONTEXT_HOURS = 48
ASK_CONTEXT_ITEMS = 15

ANON_COOKIE = "kflow_viewer"  # 与论坛匿名浏览去重共用的访客标识
ANON_COOKIE_MAX_AGE = 365 * 86400
_ANON_KEY_RE = re.compile(r"anon-[0-9a-f]{16}\Z")
QUOTA_RETENTION_DAYS = 7


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
    # 条目 category 是 AIHOT 词表；专题页按「信源分类」聚合具身智能条目。
    source_category = (request.GET.get("source_category") or "").strip()
    selected_only = request.GET.get("selected") in ("1", "true")
    try:
        limit = min(MAX_LIMIT, max(1, int(request.GET.get("limit", DEFAULT_LIMIT))))
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        limit, offset = DEFAULT_LIMIT, 0

    category_labels = dict(FeedItem.CATEGORY_CHOICES)
    qs = FeedItem.objects.select_related("source").filter(source__is_active=True)
    if source_slug:
        qs = qs.filter(source__slug=source_slug)
    if source_category:
        qs = qs.filter(source__category=source_category)
    if category:
        qs = qs.filter(category=category)
    if selected_only:
        qs = qs.filter(is_selected=True)
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
            "is_selected": item.is_selected,
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


def _ask_actor(request) -> tuple[str, str]:
    """返回 (scope, 主体标识)；管理员也按登录用户计。"""
    admin = get_admin_context(request)
    if admin:
        return FeedAskQuota.SCOPE_USER, admin["username"]
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return FeedAskQuota.SCOPE_USER, user.username
    return FeedAskQuota.SCOPE_ANON, ""


def _anon_visitor_key(request) -> tuple[str, bool]:
    """复用论坛的 kflow_viewer cookie；缺失或格式不合法时新建并标记下发给前端。"""
    raw = request.COOKIES.get(ANON_COOKIE, "")
    if _ANON_KEY_RE.fullmatch(raw):
        return raw, False
    return f"anon-{secrets.token_hex(8)}", True


class _QuotaExceeded(Exception):
    """配额不足；抛异常让外层事务把已扣的次数一并回滚。"""


def _consume_quota(scope: str, actor_key: str, window: str, limit: int) -> tuple[bool, int]:
    """原子自增一次，返回 (是否放行, 剩余次数)。

    用 ``filter(count__lt=limit).update(F+1)`` 的受影响行数判定超额：
    SQLite 下 select_for_update 无效，条件更新才是并发安全的做法
    （与 apps/personality/budget.py 的预算预留同一套手法）。
    """
    with transaction.atomic():
        row, _ = FeedAskQuota.objects.get_or_create(
            scope=scope,
            actor_key=actor_key,
            window=window,
            defaults={"count": 0},
        )
        updated = FeedAskQuota.objects.filter(pk=row.pk, count__lt=limit).update(count=F("count") + 1)
        used = FeedAskQuota.objects.filter(pk=row.pk).values_list("count", flat=True).first() or 0
    return bool(updated), max(0, limit - used)


def _reserve_ask(request, scope: str, username: str, anon_key: str):
    """扣配额，返回 (前端展示用的 quota, 已扣窗口列表)。超额抛 _QuotaExceeded。"""
    local = timezone.localtime()
    day = local.date().isoformat()
    if scope == FeedAskQuota.SCOPE_USER:
        window = local.strftime("%Y-%m-%dT%H")
        with transaction.atomic():
            allowed, remaining = _consume_quota(scope, username, window, ASK_USER_HOURLY_LIMIT)
            if not allowed:
                raise _QuotaExceeded("这一小时问得太快啦，下个整点再来～（每小时 10 次）")
        reservations = [(scope, username, window)]
        limit = ASK_USER_HOURLY_LIMIT
    else:
        ip = client_ip(request) or "unknown"
        ip_key = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]
        # cookie 维度与 IP 维度必须在同一事务里一起成功，否则回滚 cookie 配额，
        # 避免「IP 已达上限但白扣了用户的 3 次」。
        with transaction.atomic():
            allowed, remaining = _consume_quota(
                FeedAskQuota.SCOPE_ANON, anon_key, day, ASK_ANON_DAILY_LIMIT
            )
            if not allowed:
                raise _QuotaExceeded("今天的 3 次提问用完了，登录后每小时可以问 10 次～")
            ip_ok, _ = _consume_quota(
                FeedAskQuota.SCOPE_IP, ip_key, day, ASK_ANON_IP_DAILY_LIMIT
            )
            if not ip_ok:
                raise _QuotaExceeded("当前网络的游客提问次数已用完，登录后可以继续问～")
        reservations = [
            (FeedAskQuota.SCOPE_ANON, anon_key, day),
            (FeedAskQuota.SCOPE_IP, ip_key, day),
        ]
        limit = ASK_ANON_DAILY_LIMIT
    return {"scope": scope, "limit": limit, "remaining": remaining}, reservations


def _refund_ask(reservations) -> None:
    """上游模型调用失败时退还本次扣减，别让用户为服务故障买单。"""
    with transaction.atomic():
        for scope, actor_key, window in reservations:
            FeedAskQuota.objects.filter(
                scope=scope, actor_key=actor_key, window=window, count__gt=0
            ).update(count=F("count") - 1)


def _ask_response(request, scope: str, username: str, anon_key: str):
    """问小K 主流程：基于近期 AI 资讯的对话式摄入，回答带【n】引用。"""
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

    # 配置与资料都确认可用后才扣配额；模型调用失败则退还。
    try:
        quota, reservations = _reserve_ask(request, scope, username, anon_key)
    except _QuotaExceeded as exc:
        return json_error(str(exc), status=429, quota={"scope": scope, "remaining": 0})

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
        _refund_ask(reservations)
        return json_error(str(exc), status=503)
    return json_ok({"answer": answer, "refs": refs, "quota": quota})


@require_POST
def feeds_ask(request):
    """游客也能问小K；匿名身份用 kflow_viewer cookie，必要时在响应里下发。"""
    scope, username = _ask_actor(request)
    anon_key, needs_cookie = ("", False)
    if scope == FeedAskQuota.SCOPE_ANON:
        anon_key, needs_cookie = _anon_visitor_key(request)
    response = _ask_response(request, scope, username, anon_key)
    if needs_cookie:
        response.set_cookie(
            ANON_COOKIE,
            anon_key,
            max_age=ANON_COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=settings.SESSION_COOKIE_SECURE,
        )
    return response
