"""Count public page views after the response is produced.

放在中间件栈的最内层：静态资源已经被 ``StaticAssetMiddleware`` 短路，
这里只看到真正走视图的请求；同时能拿到最终状态码与 Content-Type，
只统计 ``200 + text/html`` 的 GET，304、后台与接口一概不计。
"""
from __future__ import annotations

import logging
import re

from . import services

logger = logging.getLogger(__name__)

SKIP_PREFIXES = (
    "/static/",
    "/uploads/",
    "/api/",
    "/admin",
    "/material/",
    "/.well-known/",
    "/favicon",
    "/robots.txt",
)

BOT_PATTERN = re.compile(
    r"bot|spider|crawl|slurp|preview|headless|phantomjs|lighthouse|"
    r"python-requests|curl/|wget|axios/|node-fetch|go-http-client|"
    r"okhttp|libwww|scrapy|httpclient|java/|postman",
    re.IGNORECASE,
)


class VisitStatsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        services.register_exit_flush()

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if _is_countable(request, response):
                services.record(
                    path=request.path_info,
                    referer=request.headers.get("Referer", ""),
                    ip=_client_ip(request),
                    user_agent=request.headers.get("User-Agent", ""),
                    host=_site_host(request),
                )
            services.maybe_flush()
        except Exception:
            # 统计永远不能影响业务响应。
            logger.exception("visit stats middleware failed")
        return response


def _is_countable(request, response) -> bool:
    if request.method != "GET":
        return False
    if response.status_code != 200:
        return False
    content_type = (response.get("Content-Type", "") or "").split(";")[0].strip().lower()
    if content_type != "text/html":
        return False
    path = request.path_info or "/"
    lowered = path.lower()
    if lowered.startswith(SKIP_PREFIXES):
        return False
    if request.headers.get("DNT") == "1" or request.headers.get("Sec-GPC") == "1":
        return False
    if BOT_PATTERN.search(request.headers.get("User-Agent", "")):
        return False
    return True


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def _site_host(request) -> str:
    try:
        return request.get_host()
    except Exception:
        return ""
