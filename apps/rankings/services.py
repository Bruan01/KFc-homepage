# pyright: reportMissingImports=false
"""External vibecoding project crawling (stdlib only, no extra deps)."""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import re
import ssl
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.utils import timezone as dj_timezone

from .models import CrawlRun, ExternalProject

logger = logging.getLogger(__name__)

USER_AGENT = "KFlowBot/0.1 (vibecoding community rankings)"
REQUEST_TIMEOUT = 20
GITHUB_API = "https://api.github.com"
GITHUB_TRENDING_URL = "https://github.com/trending"
KAIYUANBANG_URL = os.getenv(
    "KAIYUANBANG_URL",
    "https://kaiyuanbang.cn/zh-cn/rankings/monthly.html",
).strip() or "https://kaiyuanbang.cn/zh-cn/rankings/monthly.html"
MAX_ITEMS_PER_SOURCE = 10


def _github_token() -> str:
    return os.getenv("GITHUB_TOKEN", "").strip()


def _open_with_tls_fallback(request: Request, timeout: int):
    """Strict TLS first; on a local cert-chain failure, retry once unverified (logged)."""
    try:
        return urlopen(request, timeout=timeout)
    except URLError as exc:
        reason = str(getattr(getattr(exc, "reason", None), "reason", "") or exc.reason or "")
        if "CERTIFICATE_VERIFY_FAILED" not in reason:
            raise
        logger.warning("TLS verification failed (%s); retrying without verification", reason)
        context = ssl._create_unverified_context()  # noqa: SLF001 - degraded-mode fallback only
        return urlopen(request, timeout=timeout, context=context)


def _http_get_json(url: str, headers: dict | None = None) -> dict:
    request = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "Accept-Encoding": "gzip",
        **(headers or {}),
    })
    with _open_with_tls_fallback(request, REQUEST_TIMEOUT) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def _parse_github_datetime(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def github_heat_score(stars: int, forks: int) -> float:
    """log-normalized cross-source heat; scale ~[0, 900] for realistic star counts."""
    return round((math.log10(1 + max(0, stars)) * 2.0 + math.log10(1 + max(0, forks))) * 100, 2)


def crawl_github(run: CrawlRun) -> int:
    try:
        saved = _crawl_github_api(run)
    except HTTPError as exc:
        if exc.code in {403, 429, 401}:
            logger.warning("GitHub Search API %s; falling back to trending page", exc.code)
            saved = _crawl_github_trending(run)
        else:
            raise
    return saved


def _crawl_github_api(run: CrawlRun) -> int:
    token = _github_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    topics = ["vibe-coding", "vibecoding"]
    seen: dict[str, dict] = {}
    for topic in topics:
        url = (
            f"{GITHUB_API}/search/repositories?q={quote(f'topic:{topic}')}"
            f"&sort=stars&order=desc&per_page={MAX_ITEMS_PER_SOURCE // 2}"
        )
        data = _http_get_json(url, headers)
        for item in data.get("items", []):
            repo_id = str(item.get("id", ""))
            if not repo_id or repo_id in seen:
                continue
            seen[repo_id] = item
        run.item_count = len(seen)

    now = dj_timezone.now()
    saved = 0
    for repo_id, item in seen.items():
        stars = int(item.get("stargazers_count", 0) or 0)
        forks = int(item.get("forks_count", 0) or 0)
        license_obj = item.get("license") or {}
        metrics = {
            "stars": stars,
            "forks": forks,
            "open_issues": int(item.get("open_issues_count", 0) or 0),
            "watching": int(item.get("subscribers_count", 0) or 0),  # GitHub: subscribers ≈ Watching
            "homepage": item.get("homepage") or "",
            "license": license_obj.get("spdx_id") or "",
            "language": item.get("language") or "",
            "topic": (item.get("topics") or [""])[0] if item.get("topics") else "",
            "created_at": item.get("created_at") or "",
            "pushed_at_fact": item.get("pushed_at") or "",
            "source_page": "github_search_api",
        }
        pushed_at = _parse_github_datetime(item.get("pushed_at", "") or "")
        defaults = {
            "title": (item.get("name") or "")[:256],
            "description": (item.get("description") or "")[:1000],
            "url": item.get("html_url", ""),
            "author": (item.get("owner", {}).get("login") or "")[:190],
            "language": (item.get("language") or "")[:64],
            "metrics": json.dumps(metrics),
            "heat_score": github_heat_score(stars, forks),
            "pushed_at": pushed_at,
            "is_active": True,
            "last_crawled_at": now,
        }
        _, created = ExternalProject.objects.update_or_create(
            source=ExternalProject.SOURCE_GITHUB, external_id=repo_id, defaults=defaults
        )
        saved += 1
    # deactivate stale rows that disappeared from results
    keep_ids = list(seen.keys())
    ExternalProject.objects.filter(source=ExternalProject.SOURCE_GITHUB).exclude(external_id__in=keep_ids).update(is_active=False)
    return saved


class _TrendingParser(HTMLParser):
    """Minimal parser for github.com/trending Box-row articles."""

    REPO_RE = re.compile(r"^/(?:[^/]+/)([^/]+)$")

    def __init__(self):
        super().__init__()
        self.repos: list[dict] = []
        self._in_h2_link = False
        self._repo_href = ""
        self._current = None
        self._in_desc = False
        self._in_star_link = False
        self._in_language = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag == "h2" and "Box-row" not in classes:
            pass
        if tag == "a" and self._current is not None:
            href = attrs.get("href", "")
            if "/stargazers" in href:
                self._in_star_link = True
            elif self.REPO_RE.match(href) and href.count("/") == 2:
                self._repo_href = href
                self._in_h2_link = True
        if tag == "h2":
            self._current = {"pending": True}
        if tag == "p" and self._current is not None and "description" not in self._current and self._current.get("pending"):
            self._in_desc = True
        if tag == "span" and "d-inline-block" in classes and self._current is not None:
            self._in_language = True

    def handle_data(self, data):
        text = data.strip()
        if not text or self._current is None:
            return
        if self._in_h2_link and text and self._current.get("pending"):
            # first link inside h2 is the repo owner/name, possibly split across nodes
            self._current["full_name"] = (self._current.get("full_name", "") + text).strip()
            return
        if self._in_desc:
            self._current["description"] = text
            self._in_desc = False
            return
        if self._in_star_link:
            digits = re.sub(r"[^\d]", "", text)
            if digits:
                self._current["stars"] = int(digits)
            self._in_star_link = False
            return
        if self._in_language:
            self._current["language"] = text
            self._in_language = False

    def handle_endtag(self, tag):
        if tag == "h2" and self._current is not None:
            self._current.pop("pending", None)
            self._in_h2_link = False
        if tag == "article" and self._current is not None:
            if self._current.get("full_name"):
                self.repos.append(self._current)
            self._current = None

    def close(self):
        super().close()


def _http_get_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip"})
    with _open_with_tls_fallback(request, REQUEST_TIMEOUT) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def _crawl_github_trending(run: CrawlRun) -> int:
    """Fallback: parse the public trending page (daily)."""
    html = _http_get_text(GITHUB_TRENDING_URL)
    parser = _TrendingParser()
    parser.feed(html)
    parser.close()
    now = dj_timezone.now()
    saved = 0
    for index, repo in enumerate(parser.repos[:MAX_ITEMS_PER_SOURCE]):
        full_name = repo.get("full_name", "").lstrip("/").replace(" ", "").strip()
        if not full_name or "/" not in full_name:
            continue
        stars = int(repo.get("stars", 0) or 0)
        metrics = {"stars": stars, "trending_rank": index + 1, "source_page": "trending"}
        _, created = ExternalProject.objects.update_or_create(
            source=ExternalProject.SOURCE_GITHUB,
            external_id=full_name,  # stable: owner/name
            defaults={
                "title": full_name.split("/")[-1][:256],
                "description": (repo.get("description") or "")[:1000],
                "url": f"https://github.com/{full_name}",
                "author": full_name.split("/")[0][:190],
                "language": (repo.get("language") or "")[:64],
                "metrics": json.dumps(metrics),
                "heat_score": github_heat_score(stars, 0) + max(0, 50 - index),
                "is_active": True,
                "last_crawled_at": now,
            },
        )
        saved += 1
    run.item_count = saved
    if not saved:
        raise ValueError("trending page parsed zero repos; page structure may have changed")
    return saved


def _ph_access_token() -> str:
    """Developer token directly, or exchange API key+secret (client_credentials)."""
    token = os.getenv("PRODUCTHUNT_TOKEN", "").strip()
    if token:
        return token
    client_id = os.getenv("PRODUCTHUNT_API_KEY", "").strip()
    client_secret = os.getenv("PRODUCTHUNT_API_SECRET", "").strip()
    if not (client_id and client_secret):
        return ""
    body = urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }).encode()
    request = Request(
        "https://api.producthunt.com/v2/oauth/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
    )
    with _open_with_tls_fallback(request, REQUEST_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    access = data.get("access_token", "")
    if not access:
        raise ValueError(f"PH token exchange failed: {json.dumps(data)[:200]}")
    return access


def crawl_producthunt(run: CrawlRun) -> int:
    try:
        token = _ph_access_token()
    except (HTTPError, URLError, ValueError) as exc:
        raise ValueError(f"PH 凭据换取令牌失败: {exc}") from exc
    if not token:
        run.message = "PRODUCTHUNT_TOKEN/API_KEY 未配置，跳过（API 需在 producthunt.com 申请）"
        return 0
    # Weekly top-voted products; `topic` requires a numeric ID so we filter
    # by recency + votes instead of by topic slug.
    posted_after = (dj_timezone.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = """
    query($first: Int!, $postedAfter: DateTime!) {
      posts(first: $first, order: VOTES, postedAfter: $postedAfter) {
        edges { node { id name tagline url votesCount createdAt } }
      }
    }"""
    body = json.dumps({"query": query, "variables": {"first": MAX_ITEMS_PER_SOURCE, "postedAfter": posted_after}}).encode()
    request = Request(
        "https://api.producthunt.com/v2/api/graphql",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with _open_with_tls_fallback(request, REQUEST_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    errors = data.get("errors")
    if errors:
        raise ValueError(f"PH API error: {json.dumps(errors)[:300]}")
    now = dj_timezone.now()
    saved = 0
    for edge in data.get("data", {}).get("posts", {}).get("edges", []):
        node = edge.get("node", {})
        votes = int(node.get("votesCount", 0) or 0)
        ExternalProject.objects.update_or_create(
            source=ExternalProject.SOURCE_PRODUCTHUNT,
            external_id=node.get("id", ""),
            defaults={
                "title": (node.get("name") or "")[:256],
                "description": (node.get("tagline") or "")[:1000],
                "url": node.get("url", ""),
                "metrics": json.dumps({"upvotes": votes}),
                "heat_score": round(math.log10(1 + votes) * 200, 2),
                "is_active": True,
                "last_crawled_at": now,
            },
        )
        saved += 1
    return saved


class _KaiyuanbangParser(HTMLParser):
    """Parse kaiyuanbang.cn monthly rankings page.

    Each item is an <article class="ornav-repo ..."> with data-orank-target-key
    used as stable id. Stats live in .ornav-repo-stats (Stars / Forks / 30 日增长).
    """

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self._current: dict | None = None
        self._field: str | None = None  # which stat we are accumulating
        self._in_title = False
        self._title_buf: list[str] = []
        self._desc_buf: list[str] = []
        self._in_desc = False

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        classes = attrs_d.get("class", "")
        if tag == "article" and "ornav-repo" in classes and self._current is None:
            key = (attrs_d.get("data-orank-target-key") or "").strip()
            href = (attrs_d.get("data-orank-target-url") or "").strip()
            rank_raw = ""
            self._current = {
                "key": key,
                "href": href,
                "rank": 0,
                "language": (attrs_d.get("data-repo-language") or "").strip(),
                "topic": (attrs_d.get("data-repo-category") or "").strip(),
                "stars": 0,
                "forks": 0,
                "growth_30d": 0,
                "owner": "",
                "title": "",
                "description": "",
            }
            return
        if self._current is None:
            return
        if tag == "h3":
            self._in_title = True
        # Project description is the FIRST <p> after the title, inside .ornav-repo-main.
        # Use a class hint on the parent so we don't capture meta paragraphs (which
        # don't have a class on this site). The kaiyuanbang page emits:
        #   <div class="ornav-repo-main">
        #     <h3><a>title</a></h3>
        #     <p class="">description</p>     ← we want this one
        #     <div class="ornav-repo-meta">…</div>
        #   </div>
        if tag == "p" and not self._in_desc and self._in_title is False and self._current.get("title"):
            self._in_desc = True
        if tag == "strong":
            # number comes here (stars / forks / growth)
            self._field = "number"
            return
        if tag == "small":
            # label right after the number tells us which stat this is
            self._field = "label"
            return

    def handle_data(self, data):
        text = data.strip()
        if self._current is None:
            return
        if self._in_title:
            if text:
                self._title_buf.append(text)
            return
        if self._in_desc and text:
            self._desc_buf.append(text)
            return
        if self._field == "number" and text:
            # Number comes BEFORE its label in the HTML, so we just queue it.
            # The matching label arrives next and decides which field to fill.
            try:
                num = int(text.replace(",", ""))
            except ValueError:
                num = 0
            self._current["_pending_number"] = num
            self._field = None
            return
        if self._field == "label" and text:
            pending = self._current.pop("_pending_number", 0) or 0
            if text == "Stars":
                self._current["stars"] = pending
            elif text == "Forks":
                self._current["forks"] = pending
            elif "增长" in text:
                self._current["growth_30d"] = abs(pending)
            self._field = None
            return
        # Owner line: <bdi dir="ltr">owner/repo</bdi>
        if text and "/" in text and not self._current.get("owner"):
            # heuristic: looks like "owner/repo"
            self._current["owner"] = text[:190]

    def handle_endtag(self, tag):
        if tag == "article" and self._current is not None:
            if self._current.get("title") and self._current["key"]:
                self.items.append(self._current)
            self._current = None
            self._in_title = False
            self._in_desc = False
            self._field = None
            return
        if self._current is None:
            return
        if tag == "h3":
            if self._title_buf and not self._current.get("title"):
                self._current["title"] = "".join(self._title_buf).strip()
            self._in_title = False
            self._title_buf = []
        if tag == "p" and self._in_desc:
            if self._desc_buf and not self._current.get("description"):
                self._current["description"] = "".join(self._desc_buf).strip()
            self._in_desc = False
            self._desc_buf = []

    def close(self):
        super().close()


def _enrich_kaiyuanbang_item(item: dict, detail_html: str) -> dict:
    """Pull homepage/license/issues/watchers/created_at/24h-7d growth + 90-day
    star snapshots from a kaiyuanbang detail page and merge into the item dict.

    Source page uses these patterns:
      - <strong>Python</strong>            after orank-icon-code
      - <strong>399</strong>              after orank-icon-eye      (Watching)
      - <strong>651</strong>              after orank-icon-issue    (Issues)
      - <strong>Apache-2.0</strong>       after orank-icon-shield
      - <strong>+223</strong>             after orank-icon-trend    (24h 增长)
      - <strong>+2435</strong>            after orank-icon-trend    (7 日增长)
      - <strong>+10906</strong>           after orank-icon-trend    (30 日增长)
    Facts <dl> block has 仓库地址 / 项目官网 / 许可证 / 语言 / 最近 Push / 创建时间 / 更新时间.
    Snapshots are embedded as JSON in <script id="ornav-star-trend-data">.
    """
    def _strip_tags(s: str) -> str:
        return re.sub(r"<[^>]+>", "", s).strip()

    def _after_icon(icon_name: str) -> str | None:
        # Only look inside .ornav-metric-value blocks — buttons elsewhere reuse
        # the same icons (对比 / 纠错 use trend + issue), which would otherwise
        # steal the match.
        m = re.search(
            rf'ornav-metric-value[^>]*>.*?orank-icon-{re.escape(icon_name)}.*?'
            r'(?:<strong><bdi[^>]*>(.*?)</bdi></strong>|<strong[^>]*>(.*?)</strong>)',
            detail_html,
            re.DOTALL,
        )
        if not m:
            return None
        return _strip_tags(m.group(1) or m.group(2) or "")

    # Stat block (icon → value)
    stars_detail = _strip_tags(_after_icon("star") or "")
    forks_detail = _strip_tags(_after_icon("fork") or "")
    watching = _strip_tags(_after_icon("eye") or "")
    issues = _strip_tags(_after_icon("issue") or "")
    license_text = _strip_tags(_after_icon("shield") or "")
    language_detail = _strip_tags(_after_icon("code") or "")
    # 24h / 7d / 30d 增长(共用 trend icon;限定在 .ornav-metric-value 块内,避开按钮区)
    trend_values = re.findall(
        r'ornav-metric-value[^>]*>.*?orank-icon-trend.*?<strong[^>]*>\+?([\d,]+)</strong>',
        detail_html,
        re.DOTALL,
    )
    growth_24h = int(trend_values[0].replace(",", "")) if len(trend_values) >= 1 else 0
    growth_7d = int(trend_values[1].replace(",", "")) if len(trend_values) >= 2 else 0
    growth_30d_detail = int(trend_values[2].replace(",", "")) if len(trend_values) >= 3 else 0

    # Facts <dl>: 仓库地址 / 项目官网 / 许可证 / 语言 / 最近 Push / 创建时间 / 更新时间 / 数据同步
    def _dl_value(label: str) -> str:
        # Some <dt>s contain an icon <span><svg>...</svg></span> before the label.
        m = re.search(
            rf'<dt[^>]*>(?:<span\b[^>]*>.*?</span>\s*)?{re.escape(label)}\s*</dt>\s*<dd[^>]*>(.+?)</dd>',
            detail_html,
            re.DOTALL,
        )
        if not m:
            return ""
        return _strip_tags(m.group(1))

    homepage = ""
    m = re.search(
        r'data-orank-target-type="repo_homepage"[^>]*data-orank-target-url="([^"]+)"',
        detail_html,
    )
    if m:
        homepage = m.group(1)
    if not homepage:
        homepage = _dl_value("项目官网")
    repo_url = _dl_value("仓库地址")
    license_fact = _dl_value("许可证") or license_text
    language_fact = _dl_value("语言") or language_detail
    created_at = _dl_value("创建时间")
    pushed_at_fact = _dl_value("最近 Push") or _dl_value("更新时间")
    synced_at = _dl_value("数据同步")

    # Embedded snapshot JSON
    snapshots = []
    m = re.search(
        r'<script[^>]+id="ornav-star-trend-data"[^>]*>(.+?)</script>',
        detail_html,
        re.DOTALL,
    )
    if m:
        try:
            raw = json.loads(m.group(1))
            snapshots = [
                {"date": p.get("date", ""), "stars": int(p.get("stars") or 0),
                 "daily_growth": p.get("daily_growth")}
                for p in raw
                if p.get("date")
            ]
        except (ValueError, TypeError):
            snapshots = []

    # Prefer detail-page values over list-page when both exist
    if stars_detail and stars_detail.replace(",", "").isdigit():
        item["stars"] = int(stars_detail.replace(",", ""))
    if forks_detail and forks_detail.replace(",", "").isdigit():
        item["forks"] = int(forks_detail.replace(",", ""))
    if growth_30d_detail:
        item["growth_30d"] = growth_30d_detail

    item.update({
        "homepage": homepage[:500],
        "repo_url": repo_url[:500],
        "license": license_fact[:64],
        "language_detail": language_fact[:64],
        "watching": int(watching.replace(",", "")) if watching.replace(",", "").isdigit() else 0,
        "issues": int(issues.replace(",", "")) if issues.replace(",", "").isdigit() else 0,
        "growth_24h": growth_24h,
        "growth_7d": growth_7d,
        "created_at": created_at,
        "pushed_at_fact": pushed_at_fact,
        "synced_at": synced_at,
        "snapshots": snapshots[-90:],  # cap to last 90 days
    })
    return item


def crawl_kaiyuanbang(run: CrawlRun) -> int:
    """Crawl kaiyuanbang.cn monthly rankings page (HTML, no credentials).

    Top-N rows come from the listing page; each row is then enriched with a
    second HTTP request to its detail page (homepage/license/issues/.../snapshots).
    """
    list_html = _http_get_text(KAIYUANBANG_URL)
    parser = _KaiyuanbangParser()
    parser.feed(list_html)
    parser.close()
    now = dj_timezone.now()
    saved = 0
    seen_keys: set[str] = set()
    for index, item in enumerate(parser.items[:MAX_ITEMS_PER_SOURCE]):
        key = item.get("key", "")
        if not key:
            continue
        seen_keys.add(key)
        href = item.get("href", "") or f"/zh-cn/repo/{key}.html"
        full_url = (
            href if href.startswith("http") else f"https://kaiyuanbang.cn{href}"
        )
        # 详情页拉一次,补全字段
        try:
            detail_html = _http_get_text(full_url)
            item = _enrich_kaiyuanbang_item(item, detail_html)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("kaiyuanbang detail fetch failed for %s: %s", key, exc)

        stars = int(item.get("stars", 0) or 0)
        forks = int(item.get("forks", 0) or 0)
        growth = int(item.get("growth_30d", 0) or 0)
        # heat: log stars + log growth (growth is the "trend" signal on this site)
        heat = round(
            (math.log10(1 + stars) * 80.0 + math.log10(1 + growth) * 120.0),
            2,
        )
        metrics = {
            "stars": stars,
            "forks": forks,
            "growth_30d": growth,
            "growth_24h": int(item.get("growth_24h") or 0),
            "growth_7d": int(item.get("growth_7d") or 0),
            "watching": int(item.get("watching") or 0),
            "issues": int(item.get("issues") or 0),
            "homepage": item.get("homepage") or "",
            "repo_url": item.get("repo_url") or full_url,
            "license": item.get("license") or "",
            "language": item.get("language") or item.get("language_detail") or "",
            "topic": item.get("topic") or "",
            "created_at": item.get("created_at") or "",
            "pushed_at_fact": item.get("pushed_at_fact") or "",
            "synced_at": item.get("synced_at") or "",
            "snapshots": item.get("snapshots") or [],
            "rank": index + 1,
            "source_page": "kaiyuanbang_monthly",
        }
        # Prefer detail-page repo URL (canonical github link) when available
        canonical_url = metrics["repo_url"] or full_url
        ExternalProject.objects.update_or_create(
            source=ExternalProject.SOURCE_KAIYUANBANG,
            external_id=key,
            defaults={
                "title": (item.get("title", "") or "")[:256],
                "description": (item.get("description", "") or "")[:1000],
                "url": canonical_url[:500],
                "author": (item.get("owner", "") or "")[:190],
                "language": (item.get("language") or item.get("language_detail") or "")[:64],
                "metrics": json.dumps(metrics),
                "heat_score": heat,
                "is_active": True,
                "last_crawled_at": now,
            },
        )
        saved += 1
    run.item_count = saved
    if not saved:
        raise ValueError("kaiyuanbang page parsed zero items; page structure may have changed")
    # Deactivate rows that disappeared from the latest top-N
    ExternalProject.objects.filter(source=ExternalProject.SOURCE_KAIYUANBANG).exclude(
        external_id__in=list(seen_keys)
    ).update(is_active=False)
    return saved


CRAWLERS = {
    ExternalProject.SOURCE_KAIYUANBANG: crawl_kaiyuanbang,
}


def run_crawl(sources: list[str] | None = None, *, analyze: bool = True) -> dict[str, dict]:
    """Run crawlers with per-source run logs and failure isolation."""
    results: dict[str, dict] = {}
    wanted = sources or list(CRAWLERS.keys())
    for source in wanted:
        crawler = CRAWLERS.get(source)
        if not crawler:
            continue
        run = CrawlRun.objects.create(source=source)
        try:
            saved = crawler(run)
            run.status = CrawlRun.STATUS_SUCCESS
            run.item_count = saved
            results[source] = {"status": "success", "count": saved, "message": run.message}
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            run.status = CrawlRun.STATUS_FAILED
            run.message = f"{type(exc).__name__}: {exc}"[:2000]
            results[source] = {"status": "failed", "message": run.message}
            logger.warning("crawl failed for %s: %s", source, exc)
        finally:
            run.finished_at = dj_timezone.now()
            run.save(update_fields=["status", "item_count", "message", "finished_at"])

    if analyze and any(r["status"] == "success" for r in results.values()):
        try:
            from .analysis import analyze_top_projects, snapshot_metrics

            snapshotted = snapshot_metrics()
            analyzed = analyze_top_projects()
            logger.info("rankings analysis: %s metric snapshots, %s projects analyzed", snapshotted, analyzed)
            for item in results.values():
                if item["status"] == "success":
                    item["analysis"] = {"snapshots": snapshotted, "analyzed": analyzed}
        except Exception as exc:
            logger.warning("rankings analysis skipped: %s", exc)
    return results
