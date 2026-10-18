"""Middleware that upgrades still-valid legacy sessions into Django sessions."""
from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import login

from apps.accounts.models import AdminAccount, LegacySession, User
from apps.core import pages


class StaticAssetMiddleware:
    """Serve static/media assets before the session stack ever runs.

    一个页面会拉几十个 .css/.js/.webp，这些请求全都带着本站 cookie 出门。
    走完整中间件栈意味着每个资源都可能触发 LegacySession 的表查询和 CSRF
    处理，而这两件事对静态资源毫无意义。

    更关键的是响应头：CsrfViewMiddleware 会给**每一个**响应打上
    ``Vary: Cookie``，于是同一份 CSS 在浏览器/CDN 里按 cookie 切成多份副本，
    Cloudflare 这类共享缓存遇到 Vary: Cookie 往往直接不缓存。这里在最后
    一道 process_response 里把 Cookie 从 Vary 中摘掉，只保留真正影响编码
    的 Accept-Encoding。
    """

    # 请求侧直接短路的前缀。 uploads/ 刻意不在其中：显影模板封面有自己的
    # 视图（需要登录、private 缓存），短路会抢掉它的路由。
    SHORT_CIRCUIT_PREFIXES = ("static/", "material/")
    # 响应侧清理 Vary 的范围，比短路范围宽——公开上传物同样不该按 cookie 分裂。
    CACHEABLE_PREFIXES = ("static/", "uploads/", "material/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = None
        if self._enabled() and request.method in ("GET", "HEAD"):
            response = self._serve(request)
        if response is None:
            response = self.get_response(request)
        return self._harden_headers(request, response)

    # ── request side ──────────────────────────────────────────────────────
    @staticmethod
    def _enabled() -> bool:
        return bool(getattr(settings, "STATIC_ASSET_SHORTCIRCUIT", True))

    def _serve(self, request):
        path = request.path_info.lstrip("/")
        if not path or ".." in path:
            return None
        lowered = path.lower()
        for prefix in self.SHORT_CIRCUIT_PREFIXES:
            if lowered.startswith(prefix):
                asset = path[len(prefix):]
                if not asset:
                    return None
                view = {
                    "static/": pages.static_asset,
                    "material/": pages.material_file,
                }[prefix]
                return view(request, asset_path=asset)
        # 站点根下的裸文件名（/favicon.svg、/robots.txt）同样直接返回，
        # .html 页面刻意排除——它们要过 CsrfViewMiddleware 种 cookie。
        if "/" not in path and path.rsplit(".", 1)[-1].lower() in self._suffixes():
            return pages.static_asset(request, asset_path=path)
        return None

    @staticmethod
    def _suffixes():
        return {s.lstrip(".") for s in pages.TOPLEVEL_STATIC_SUFFIXES}

    # ── response side ─────────────────────────────────────────────────────
    CACHE_FRIENDLY_TYPES = (
        "image/", "video/", "audio/", "font/",
        "application/font-woff", "application/font-woff2",
        "application/x-font-ttf", "application/vnd.ms-fontobject",
    )

    def _harden_headers(self, request, response):
        if not self._should_strip_cookie(request, response):
            return response
        vary = [
            item.strip()
            for item in response.get("Vary", "").split(",")
            if item.strip() and item.strip().lower() != "cookie"
        ]
        if response.get("Content-Encoding") and "Accept-Encoding" not in vary:
            vary.append("Accept-Encoding")
        if vary:
            response["Vary"] = ", ".join(vary)
        elif "Vary" in response:
            del response["Vary"]
        return response

    @classmethod
    def _should_strip_cookie(cls, request, response) -> bool:
        """只摘掉「内容不随 cookie 变化」的响应上的 Vary: Cookie。

        两条红线：
        - 页面和 JSON 接口的正文可能随登录态变化，摘掉 Vary 会让缓存把 A 用户
          的响应发给 B 用户，所以它们必须原样保留；
        - 显式声明 ``private`` / ``no-store`` 的响应是视图作者主动拒绝共享缓存
          （显影图片按用户隔离就是这么做的），这里不再替它做优化。
        """
        control = response.get("Cache-Control", "").lower()
        if "private" in control or "no-store" in control:
            return False
        content_type = response.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type.startswith(cls.CACHE_FRIENDLY_TYPES):
            return bool(response.get("Cache-Control"))
        return cls._is_asset_path(request.path_info)

    @classmethod
    def _is_asset_path(cls, path_info: str) -> bool:
        path = path_info.lstrip("/")
        if not path:
            return False
        lowered = path.lower()
        if lowered.startswith(cls.CACHEABLE_PREFIXES):
            return True
        if "/" in path:
            return False
        suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        return suffix in {s.lstrip(".") for s in pages.TOPLEVEL_STATIC_SUFFIXES}


class LegacySessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._upgrade(request)
        return self.get_response(request)

    def _upgrade(self, request):
        if request.user.is_authenticated or request.session.get("admin_username"):
            return
        raw_tokens = [
            request.COOKIES.get(settings.SESSION_COOKIE_NAME, ""),
            request.COOKIES.get(settings.ADMIN_SESSION_COOKIE, ""),
        ]
        for token in filter(None, raw_tokens):
            legacy = LegacySession.objects.filter(token=token).first()
            if not legacy:
                continue
            if float(legacy.exp) < time.time():
                legacy.delete()
                continue
            if legacy.role == "user" and legacy.user_id:
                user = User.objects.filter(pk=legacy.user_id).first()
                if not user:
                    continue
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                self._set_admin_from_user(request, user)
                legacy.delete()
                return
            if legacy.role == "admin":
                request.session.cycle_key()
                request.session["admin_username"] = legacy.username
                request.session["admin_level"] = int(legacy.admin_level or 1)
                request.session["admin_is_super"] = bool(legacy.is_super)
                legacy.delete()
                return

    @staticmethod
    def _set_admin_from_user(request, user):
        if user.username == settings.ADMIN_USERNAME:
            request.session["admin_username"] = user.username
            request.session["admin_level"] = 3
            request.session["admin_is_super"] = True
            return
        admin = AdminAccount.objects.filter(username=user.username).first()
        if admin:
            request.session["admin_username"] = admin.username
            request.session["admin_level"] = int(admin.admin_level or 1)
            request.session["admin_is_super"] = bool(admin.is_super)
