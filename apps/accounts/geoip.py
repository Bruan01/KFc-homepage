"""Province-level IP location for the account settings page.

Loopback and private addresses never leave the server. Public addresses are
resolved through Baidu's open IP API (accurate for mainland China) and fall
back to ip-api.com (covers IPv6, which Baidu does not answer). Results are
cached so each visitor IP costs at most one upstream call per week.
"""
from __future__ import annotations

import ipaddress
import json
import urllib.parse
import urllib.request

from django.core.cache import cache

CACHE_SECONDS = 7 * 24 * 3600
FAILURE_CACHE_SECONDS = 600
UNKNOWN = "未知"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_AUTONOMOUS_PREFIXES = ("壮族", "回族", "维吾尔")


def ip_province(ip: str) -> str:
    if not ip:
        return UNKNOWN
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return UNKNOWN
    if address.is_loopback:
        return "本机"
    if address.is_private:
        return "内网"
    key = f"geoip:province:{ip}"
    cached = cache.get(key)
    if cached:
        return cached
    location = _from_baidu(ip) or _from_ipapi(ip) or UNKNOWN
    cache.set(key, location, CACHE_SECONDS if location != UNKNOWN else FAILURE_CACHE_SECONDS)
    return location


def _normalize(raw: str) -> str:
    text = (raw or "").strip().split(" ", 1)[0]
    if not text:
        return ""
    markers = [(text.find(marker), marker) for marker in ("特别行政区", "自治区", "省", "市")]
    markers = [(index, marker) for index, marker in markers if index > 0]
    if not markers:
        return text
    index, marker = min(markers)
    name = text[:index]
    if marker == "自治区":
        for prefix in _AUTONOMOUS_PREFIXES:
            if name.endswith(prefix):
                name = name[: -len(prefix)]
    return name


def _get_json(url: str, timeout: float) -> dict:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(65536).decode("utf-8", "replace"))
    except Exception:
        return {}


def _from_baidu(ip: str) -> str:
    url = "https://opendata.baidu.com/api.php?" + urllib.parse.urlencode(
        {"query": ip, "co": "", "resource_id": "6006", "oe": "utf8"}
    )
    entries = _get_json(url, timeout=2.0).get("data") or []
    return _normalize(entries[0].get("location") or "") if entries else ""


def _from_ipapi(ip: str) -> str:
    url = (
        f"http://ip-api.com/json/{urllib.parse.quote(ip, safe=':')}"
        "?lang=zh-CN&fields=status,country,regionName"
    )
    payload = _get_json(url, timeout=1.5)
    if payload.get("status") != "success":
        return ""
    country = payload.get("country") or ""
    region = payload.get("regionName") or ""
    return region if country == "中国" and region else country or region
