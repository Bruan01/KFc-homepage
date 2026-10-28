"""页面与来源的中文命名。

后台要显示的是「首页 / 显影 / 论坛」这类界面名称，不是 /product/xxx 这种
路径；动态页面按前缀归组，避免热门榜被几百条详情 URL 冲散。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

# page_key -> (中文名, 展示用路径)
PAGE_META: dict[str, tuple[str, str]] = {
    "home": ("首页", "/"),
    "products": ("产品站", "/products"),
    "product_detail": ("产品详情", "/product/*"),
    "feeds": ("AI 电讯", "/feeds"),
    "forum": ("论坛", "/forum"),
    "forum_profile": ("社区主页", "/forum/user/*"),
    "topic_share": ("帖子分享", "/t/*"),
    "murmurs": ("碎碎念", "/murmurs"),
    "imaging": ("显影", "/imaging"),
    "rankings": ("榜单", "/rankings"),
    "ranking_project": ("榜单项目", "/rankings/project/*"),
    "glossary": ("词条", "/glossary"),
    "glossary_detail": ("词条详情", "/glossary/*"),
    "achievements": ("成就", "/achievements"),
    "levels": ("等级", "/levels"),
    "guide": ("指南", "/guide"),
    "tutorials": ("教程", "/tutorials"),
    "tutorial_detail": ("教程详情", "/tutorials/*"),
    "site_stats": ("社区数据", "/stats"),
    "points": ("积分", "/points"),
    "store": ("K 士多", "/store"),
    "messages": ("消息", "/messages"),
    "account": ("个人中心", "/account"),
    "account_settings": ("账号设置", "/account/settings"),
    "login": ("登录页", "/login"),
    "terminal": ("小屏终端", "/terminal"),
    "terminal_reserve": ("终端预约", "/terminal/reserve"),
    "cardloom": ("Cardloom", "/cardloom"),
    "service_status": ("服务状态", "/service-status"),
    "newapi": ("NewAPI 状态", "/newapi"),
    "other": ("其他页面", "—"),
}

_PAGE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/$"), "home"),
    (re.compile(r"^/products$"), "products"),
    (re.compile(r"^/product/[^/]+$"), "product_detail"),
    (re.compile(r"^/feeds$"), "feeds"),
    (re.compile(r"^/forum$"), "forum"),
    (re.compile(r"^/forum/user/[^/]+$"), "forum_profile"),
    (re.compile(r"^/t/\d+$"), "topic_share"),
    (re.compile(r"^/murmurs$"), "murmurs"),
    (re.compile(r"^/imaging$"), "imaging"),
    (re.compile(r"^/rankings$"), "rankings"),
    (re.compile(r"^/rankings/project/[^/]+$"), "ranking_project"),
    (re.compile(r"^/glossary$"), "glossary"),
    (re.compile(r"^/glossary/[^/]+$"), "glossary_detail"),
    (re.compile(r"^/achievements$"), "achievements"),
    (re.compile(r"^/levels$"), "levels"),
    (re.compile(r"^/guide$"), "guide"),
    (re.compile(r"^/tutorials$"), "tutorials"),
    (re.compile(r"^/tutorials/[^/]+$"), "tutorial_detail"),
    (re.compile(r"^/stats$"), "site_stats"),
    (re.compile(r"^/points$"), "points"),
    (re.compile(r"^/store$"), "store"),
    (re.compile(r"^/messages$"), "messages"),
    (re.compile(r"^/account/settings$"), "account_settings"),
    (re.compile(r"^/account$"), "account"),
    (re.compile(r"^/login$"), "login"),
    (re.compile(r"^/terminal$"), "terminal"),
    (re.compile(r"^/terminal/reserve$"), "terminal_reserve"),
    (re.compile(r"^/cardloom$"), "cardloom"),
    (re.compile(r"^/service-status$"), "service_status"),
    (re.compile(r"^/newapi$"), "newapi"),
]

SOURCE_LABELS: dict[str, str] = {
    "direct": "直接访问",
    "internal": "站内跳转",
    "wechat": "微信",
    "qq": "QQ",
    "weibo": "微博",
    "zhihu": "知乎",
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "bilibili": "哔哩哔哩",
    "toutiao": "今日头条",
    "baidu": "百度",
    "google": "谷歌",
    "bing": "必应",
    "sogou": "搜狗",
    "so360": "360 搜索",
    "github": "GitHub",
    "x": "X",
    "telegram": "Telegram",
}

# 顺序重要：weixin.qq.com 同时命中 qq.com，微信必须排在 QQ 前面。
_SOURCE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("wechat", ("weixin.qq.com", "wechat.com", "weixin.com", "wework.com")),
    ("qq", ("qq.com", "qzone.qq.com")),
    ("weibo", ("weibo.com", "weibo.cn")),
    ("zhihu", ("zhihu.com",)),
    ("douyin", ("douyin.com",)),
    ("xiaohongshu", ("xiaohongshu.com", "xhslink.com")),
    ("bilibili", ("bilibili.com", "b23.tv")),
    ("toutiao", ("toutiao.com",)),
    ("baidu", ("baidu.com", "bdurl.net")),
    ("google", ("google.com", "google.com.hk", "google.co.jp", "google.co.uk", "googleapis.com")),
    ("bing", ("bing.com", "msn.com")),
    ("sogou", ("sogou.com",)),
    ("so360", ("so.com", "360.cn", "haosou.com")),
    ("github", ("github.com", "github.io")),
    ("x", ("x.com", "twitter.com", "t.co")),
    ("telegram", ("telegram.org", "t.me")),
]


def classify_page(path: str) -> str:
    normalized = path if path == "/" else path.rstrip("/")
    if not normalized:
        normalized = "/"
    for pattern, key in _PAGE_RULES:
        if pattern.match(normalized):
            return key
    return "other"


def page_label(key: str) -> str:
    return PAGE_META.get(key, PAGE_META["other"])[0]


def page_path(key: str) -> str:
    return PAGE_META.get(key, PAGE_META["other"])[1]


def classify_referrer(referer: str, site_host: str) -> str:
    if not referer:
        return "direct"
    try:
        parsed = urlsplit(referer)
    except ValueError:
        return "direct"
    host = (parsed.hostname or "").lower()
    if not host:
        return "direct"
    own = (site_host or "").split(":")[0].lower()
    if host == own or host == f"www.{own}":
        return "internal"
    for key, domains in _SOURCE_RULES:
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return key
    return host[4:] if host.startswith("www.") else host


def source_label(key: str) -> str:
    if key in SOURCE_LABELS:
        return SOURCE_LABELS[key]
    return key or "其他来源"
