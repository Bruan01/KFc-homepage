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
MAX_ITEMS_PER_SOURCE = 50


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
        metrics = {
            "stars": stars,
            "forks": forks,
            "open_issues": int(item.get("open_issues_count", 0) or 0),
            "watchers": int(item.get("watchers_count", 0) or 0),
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
    body = json.dumps({"query": query, "variables": {"first": 30, "postedAfter": posted_after}}).encode()
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


def crawl_cn_community(run: CrawlRun) -> int:
    # V2EX hot topics endpoint is public and needs no credentials;
    # override with V2EX_HOT_URL to point at any JSON hot-list instead.
    url = os.getenv("V2EX_HOT_URL", "").strip() or "https://www.v2ex.com/api/topics/hot.json"
    data = _http_get_json(url)
    now = dj_timezone.now()
    saved = 0
    for item in data[:MAX_ITEMS_PER_SOURCE]:
        replies = int(item.get("replies", 0) or 0)
        external_id = str(item.get("id", ""))
        if not external_id:
            continue
        ExternalProject.objects.update_or_create(
            source=ExternalProject.SOURCE_CN_COMMUNITY,
            external_id=external_id,
            defaults={
                "title": (item.get("title") or "")[:256],
                "description": "",
                "url": item.get("url", ""),
                "author": (item.get("member", {}).get("username") or "")[:190],
                "metrics": json.dumps({"replies": replies}),
                "heat_score": round(math.log10(1 + replies) * 150, 2),
                "is_active": True,
                "last_crawled_at": now,
            },
        )
        saved += 1
    return saved


CRAWLERS = {
    ExternalProject.SOURCE_GITHUB: crawl_github,
    ExternalProject.SOURCE_PRODUCTHUNT: crawl_producthunt,
    ExternalProject.SOURCE_CN_COMMUNITY: crawl_cn_community,
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
