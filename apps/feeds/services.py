# pyright: reportMissingImports=false
"""Feed fetching: RSS/Atom via stdlib (no extra deps), per-source isolation.

企业通行做法：只聚合元数据（标题/链接/摘要/时间），原文永远留在来源
站点——摘要截断、点击跳转、来源显著标注。
"""
from __future__ import annotations

import html
import json
import logging
import re
import ssl
import time
from datetime import timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime as parse_iso_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import FeedFetchRun, FeedItem, FeedSource

logger = logging.getLogger(__name__)

FEED_TIMEOUT = 20
MAX_ITEMS_PER_FETCH = 30
SUMMARY_MAX_CHARS = 300
ITEM_RETENTION_DAYS = 45
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) KFlowFeeds/1.0"

# AIHOT 公开 API（无需 key，带 ETag/304 节流；429/503 带 Retry-After）。
# 主流抓"全部动态"（mode=all，最近 7 天持续更新）；实测该流的 selected 字段
# 恒为 false，所以精选状态单独用 mode=selected 流补齐——两流按 (source, guid)
# upsert 到同一信源下，精选流在后跑，保证标记落在最终状态。
AIHOT_ITEMS_URL = "https://aihot.news/api/v1/items?mode=all&limit=100"
AIHOT_SELECTED_URL = "https://aihot.news/api/v1/items?mode=selected&limit=100"
AIHOT_HOT_URL = "https://aihot.news/api/v1/hot-topics"
AIHOT_CATEGORY_MAP = {
    "ai-models": FeedItem.CATEGORY_MODEL,
    "ai-products": FeedItem.CATEGORY_PRODUCT,
    "industry": FeedItem.CATEGORY_INDUSTRY,
    "paper": FeedItem.CATEGORY_PAPER,
    "tip": FeedItem.CATEGORY_TIP,
    "opinion": FeedItem.CATEGORY_OPINION,
}
# ETag 按抓取 URL 隔离，避免不同流之间误用对方的校验值。
_aihot_etags: dict[str, str | None] = {}

ATOM_NS = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _open_with_tls_fallback(request: Request, timeout: int):
    try:
        return urlopen(request, timeout=timeout)
    except URLError:
        # 个别站点（自签/旧 TLS）需要放宽校验才能抓到；只影响抓取进程。
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return urlopen(request, timeout=timeout, context=context)


def _http_get(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    with _open_with_tls_fallback(request, FEED_TIMEOUT) as response:
        return response.read()


def _strip_html(text: str) -> str:
    if not text:
        return ""
    # CDATA 内容里也是 HTML 片段，去标签 + 反转实体后截断。
    cleaned = html.unescape(_TAG_RE.sub(" ", text))
    return _WS_RE.sub(" ", cleaned).strip()[:SUMMARY_MAX_CHARS]


def _parse_datetime(value: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)  # RFC 822（RSS pubDate）
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dj_timezone.get_current_timezone())
        return parsed
    except (ValueError, TypeError):
        pass
    try:
        parsed = parse_iso_datetime(value)  # ISO 8601（Atom）
        if parsed is not None:
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dj_timezone.get_current_timezone())
            return parsed
    except (ValueError, TypeError):
        pass
    return None


def _local(tag: str) -> str:
    """Namespace-agnostic tag name ({ns}name -> name)."""
    return tag.rsplit("}", 1)[-1].lower()


def _find_all(root: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in root.iter() if _local(child.tag) == name]


def _first_text(node: ElementTree.Element, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for child in node:
        if _local(child.tag) in wanted:
            return (child.text or "").strip()
    return ""


def _entry_link(node: ElementTree.Element) -> str:
    # Atom 的 <link rel="alternate" href> 与 RSS 的 <link>文本</link> 结构不同。
    for child in node:
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        rel = (child.get("rel") or "alternate").lower()
        if href and rel == "alternate":
            return href.strip()
        if href and not child.get("rel"):
            return href.strip()
        if not href and (child.text or "").strip().startswith("http"):
            return child.text.strip()
    return _first_text(node, "link")


def parse_feed(xml_text: str | bytes) -> list[dict]:
    """Parse RSS 2.0 / Atom into entry dicts (title/url/summary/guid/published_at)."""
    root = ElementTree.fromstring(xml_text)
    entries = []
    nodes = _find_all(root, "item") or _find_all(root, "entry")
    for node in nodes:
        title = _first_text(node, "title")
        url = _entry_link(node)
        if not title or not url:
            continue
        summary = _strip_html(_first_text(node, "description", "summary", "content"))
        published_raw = _first_text(node, "pubDate", "published", "updated", "dc:date")
        guid = _first_text(node, "guid", "id") or url
        entries.append(
            {
                "title": _WS_RE.sub(" ", html.unescape(title)).strip()[:500],
                "url": url[:1000],
                "summary": summary,
                "guid": guid[:500],
                "published_at": _parse_datetime(published_raw),
            }
        )
    return entries[:MAX_ITEMS_PER_FETCH]


def fetch_source(source: FeedSource, run: FeedFetchRun) -> int:
    """Fetch one source and store new items. Returns created count."""
    if source.fetch_kind == "api_aihot":
        return fetch_aihot_items(source)
    xml_bytes = _http_get(source.feed_url)
    entries = parse_feed(xml_bytes)
    created = 0
    now = dj_timezone.now()
    for entry in entries:
        _, was_created = FeedItem.objects.get_or_create(
            source=source,
            guid=entry["guid"],
            defaults={
                "title": entry["title"],
                "url": entry["url"],
                "summary": entry["summary"],
                "language": source.language,
                "published_at": entry["published_at"] or now,
            },
        )
        created += int(was_created)
    return created


def fetch_aihot_items(source: FeedSource) -> int:
    """Fetch AIHOT: 全部动态时间流 + 精选标记补齐，返回新建条数。

    时间流 URL 取自 source.feed_url；精选流失败只记日志不判整次失败
    （时间流已入库，下次抓取会再补标记）。
    """
    created = _fetch_aihot_url(source, source.feed_url or AIHOT_ITEMS_URL, mark_selected=False)
    try:
        created += _fetch_aihot_url(source, AIHOT_SELECTED_URL, mark_selected=True)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        logger.warning("feed fetch: aihot selected pass failed for %s: %s", source.slug, exc)
    return created


def _fetch_aihot_url(source: FeedSource, fetch_url: str, mark_selected: bool) -> int:
    """Fetch one AIHOT API URL with ETag revalidation and upsert its items."""
    etag = _aihot_etags.get(fetch_url)
    request = Request(
        fetch_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        | ({"If-None-Match": etag} if etag else {}),
    )
    with _open_with_tls_fallback(request, FEED_TIMEOUT) as response:
        if response.status == 304:
            return 0
        if response.headers.get("ETag"):
            _aihot_etags[fetch_url] = response.headers["ETag"]
        payload = json.loads(response.read().decode("utf-8"))
    created = 0
    now = dj_timezone.now()
    for raw in payload.get("items", []):
        links = raw.get("links") or {}
        url = links.get("original") or links.get("aihot") or ""
        guid = raw.get("id") or url
        if not raw.get("title") or not guid:
            continue
        defaults = {
            "title": _WS_RE.sub(" ", raw["title"]).strip()[:500],
            "url": url[:1000],
            "summary": _strip_html(raw.get("summary") or "")[:1000],
            "language": "zh",
            "published_at": _parse_datetime(raw.get("publishedAt") or raw.get("discoveredAt")) or now,
            "category": AIHOT_CATEGORY_MAP.get(raw.get("category") or "", ""),
            "is_selected": bool(raw.get("selected")) or mark_selected,
            "score": max(0, min(100, int(raw.get("score") or 0))),
            "upstream_name": (raw.get("source") or {}).get("name", "")[:190],
            "via_name": (raw.get("attribution") or {}).get("name", "AIHOT")[:64],
            "via_url": (raw.get("attribution") or {}).get("url") or links.get("aihot") or "https://aihot.news/",
        }
        _, was_created = FeedItem.objects.update_or_create(
            source=source,
            guid=guid[:500],
            defaults=defaults,
        )
        created += int(was_created)
    return created


def fetch_aihot_hot_topics() -> list[dict]:
    """Fetch current hot topics for the page rail (best effort)."""
    request = Request(AIHOT_HOT_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with _open_with_tls_fallback(request, FEED_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [
        {
            "rank": int(topic.get("rank") or 0),
            "title": (topic.get("title") or "")[:300],
            "source": (topic.get("source") or {}).get("name", ""),
            "url": (topic.get("links") or {}).get("original") or (topic.get("links") or {}).get("aihot") or "",
            "signal_count": int(topic.get("signalCount") or 0),
            "source_count": int(topic.get("sourceCount") or 0),
        }
        for topic in payload.get("items", [])
        if topic.get("title")
    ]


def prune_items(retention_days: int = ITEM_RETENTION_DAYS) -> int:
    cutoff = dj_timezone.now() - timedelta(days=retention_days)
    deleted, _ = FeedItem.objects.filter(published_at__lt=cutoff).delete()
    return deleted


def run_fetch(slugs: list[str] | None = None) -> dict[str, dict]:
    """Fetch feeds with per-source run logs and failure isolation (like run_crawl)."""
    results: dict[str, dict] = {}
    qs = FeedSource.objects.filter(is_active=True).exclude(feed_url="")
    if slugs:
        qs = qs.filter(slug__in=slugs)
    for source in qs:
        run = FeedFetchRun.objects.create(source_slug=source.slug)
        try:
            created = fetch_source(source, run)
            run.status = FeedFetchRun.STATUS_SUCCESS
            run.item_count = created
            results[source.slug] = {"status": "success", "count": created}
        except (HTTPError, URLError, TimeoutError, ValueError, OSError, ElementTree.ParseError) as exc:
            run.status = FeedFetchRun.STATUS_FAILED
            run.message = f"{type(exc).__name__}: {exc}"[:2000]
            results[source.slug] = {"status": "failed", "message": run.message}
            logger.warning("feed fetch failed for %s: %s", source.slug, exc)
        finally:
            run.finished_at = dj_timezone.now()
            run.save(update_fields=["status", "item_count", "message", "finished_at"])
            if run.status == FeedFetchRun.STATUS_SUCCESS:
                source.last_fetched_at = run.finished_at
                source.save(update_fields=["last_fetched_at"])
    return results
