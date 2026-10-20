# pyright: reportMissingImports=false

"""Serve the existing static HTML application through Django."""
from __future__ import annotations

import gzip
import hashlib
import io
import mimetypes
import re
import threading
from pathlib import Path

from django.conf import settings
from django.http import (
    FileResponse,
    Http404,
    HttpResponseForbidden,
    HttpResponseNotModified,
)
from django.shortcuts import redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET

from .permissions import get_admin_context

PAGE_MAP = {
    "": "index.html",
    "login": "user-login.html",
    "account": "account.html",
    "points": "points.html",
    "store": "store.html",
    "forum": "forum.html",
    "murmurs": "murmurs.html",
    "forum/user": "forum-profile.html",
    "rankings": "rankings.html",
    "glossary": "glossary.html",
    "achievements": "achievements.html",
    "levels": "levels.html",
    "stats": "stats.html",
    "guide": "guide.html",
    "tutorials": "tutorials.html",
    "tutorials/detail": "tutorial-detail.html",
    "products": "products.html",
    "admin": "admin.html",
    "admin/products": "admin.html",
    "admin/reviews": "admin.html",
    "admin/points": "admin.html",
    "admin/store": "admin.html",
    "admin/imaging": "admin.html",
    "admin/forum": "admin.html",
    "admin/users": "admin.html",
    "admin/rankings": "admin.html",
    "admin/learn": "admin.html",
    "admin/listings": "admin.html",
    "admin/settings": "admin.html",
    "admin/bigscreen": "admin-bigscreen.html",
    "cardloom": "cardloom_official_website.html",
    "service-status": "newapi-status.html",
    "newapi": "newapi-status.html",
}


def _safe_static_path(relative):
    root = (settings.BASE_DIR / "static").resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise Http404 from exc
    if not target.is_file():
        raise Http404
    return target


IMMUTABLE_SUFFIXES = {
    ".css", ".js", ".svg", ".webp", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".woff", ".woff2", ".ttf", ".mp4",
}
INLINE_MAX_BYTES = 512 * 1024

COMPRESSIBLE_SUFFIXES = {".html", ".css", ".js", ".svg", ".json", ".txt", ".xml"}

# 公开可读的上传物：图片与短视频。发布包（.zip/.apk/...）不在其中——它们
# 走 /api/downloads 的鉴权接口，不能因为目录被公开就绕过积分校验。
MEDIA_SERVED_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif",
    ".svg", ".ico", ".mp4", ".webm", ".mov",
}

# 站点根目录里可以直接短路给静态视图的扩展名（不含 .html：页面要种 CSRF cookie）。
TOPLEVEL_STATIC_SUFFIXES = {
    ".css", ".js", ".mjs", ".svg", ".ico", ".png", ".jpg", ".jpeg",
    ".webp", ".gif", ".avif", ".woff", ".woff2", ".ttf", ".otf",
    ".mp4", ".webm", ".txt",
}

_asset_version_cache: dict[str, tuple[tuple[int, int], str]] = {}
_html_cache: dict[str, tuple[tuple[int, int], bytes]] = {}
_structure_cache: dict[str, tuple[tuple[int, int], list[str], list[str]]] = {}
_gzip_cache: dict[str, tuple[tuple[int, int], bytes]] = {}
_cache_lock = threading.Lock()

_asset_ref_re = re.compile(rb'(href|src)="/([^"?]+\.(?:css|js))(?:\?[^"]*)?"')
_inline_scripts_re = re.compile(
    rb'[ \t]*<script src="/(theme|icons|csrf)\.js(?:\?v=[0-9a-f]+)?"[^>]*></script>\n?'
)


def _signature(target: Path) -> tuple[int, int]:
    stat = target.stat()
    return (stat.st_size, int(stat.st_mtime))


def asset_version(relative: str) -> str:
    """Short content hash used as a cache-busting query string."""
    try:
        target = _safe_static_path(relative)
    except Http404:
        return "0"
    signature = _signature(target)
    cached = _asset_version_cache.get(relative)
    if cached is not None and cached[0] == signature:
        return cached[1]
    digest = hashlib.sha256(target.read_bytes()).hexdigest()[:12]
    with _cache_lock:
        _asset_version_cache[relative] = (signature, digest)
    return digest


def _replace_asset_ref(match: "re.Match[bytes]") -> bytes:
    attr = match.group(1)
    path = match.group(2).decode("utf-8", "ignore")
    # Assets are also reachable under /static/, where that prefix is stripped
    # before resolution. Normalise so the version lookup finds the real file.
    lookup = path[len("static/") :] if path.startswith("static/") else path
    return b'%s="/%s?v=%s"' % (
        attr,
        path.encode("utf-8"),
        asset_version(lookup).encode("ascii"),
    )


def _inline_block(match: "re.Match[bytes]") -> bytes:
    """Inline a render-blocking script so it costs no extra round trip."""
    name = match.group(1).decode("ascii")
    try:
        payload = _safe_static_path(name + ".js").read_bytes()
    except Http404:
        return match.group(0)
    if b"</script" in payload.lower():
        return match.group(0)
    label = ("/" + name + ".js").encode("utf-8")
    return b"<script>/* " + label + b" */\n" + payload + b"\n</script>\n"


def _rendered_html(target: Path, signature: tuple[int, int]) -> bytes:
    """Render a static HTML page.

    Appends ``?v=<content-hash>`` to local css/js references so those assets
    can be cached immutably, and inlines the small render-blocking scripts
    (theme/icons) so first paint does not wait on extra round trips.

    The cache key must include the signatures of the *referenced* assets too:
    the browser holds ``?v=<hash>`` URLs under ``immutable``, so a stale hash
    would pin an old stylesheet until the HTML itself changed. Keying on the
    html file alone caused exactly that after every CSS rebuild.
    """
    refs, inline_names = _page_structure(target, signature)
    # 被引用资源的内容签名拼进 key：任何一个 css/js 变了，HTML 立即重渲染。
    parts = [signature]
    for ref in refs:
        lookup = ref[len("static/"):] if ref.startswith("static/") else ref
        try:
            parts.append(_signature(_safe_static_path(lookup)))
        except Http404:
            continue
    for name in inline_names:
        try:
            parts.append(_signature(_safe_static_path(name + ".js")))
        except Http404:
            continue
    key = str(target) + "|" + ",".join(str(p) for p in parts)
    # key 必须在做改动之前算完：以前这里先 sub() 再查缓存，命中时虽然返回了旧结果，
    # 但本次的 read_bytes + 十几次正则替换 + 内联脚本读盘已经白做了 —— 每个页面
    # 17~22 ms 的纯浪费（forum.html 实测）。
    cached = _html_cache.get(key)
    if cached is not None:
        return cached
    raw = target.read_bytes()
    rendered = _asset_ref_re.sub(_replace_asset_ref, raw)
    rendered = _inline_scripts_re.sub(_inline_block, rendered)
    # 部署产物变化会让 key 无限累积，超出上限直接整表清空（HTML 渲染本身很便宜）。
    if len(_html_cache) > 64:
        _html_cache.clear()
    with _cache_lock:
        _html_cache[key] = rendered
    return rendered


def _page_structure(target: Path, signature: tuple[int, int]) -> tuple[list[str], list[str]]:
    """缓存「这个页面引用了哪些资源」。

    签名必须在任何改写之前收集：内联脚本被替换掉之后就再也扫不到了（曾经因此在
    改写后的 bytes 上收集，导致 theme.js 的改动永远不会让 key 变化）。这里把扫描
    结果连同文件签名一起缓存，缓存命中时连 read_bytes 都不用做。
    """
    key = str(target)
    cached = _structure_cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1], cached[2]
    raw = target.read_bytes()
    refs = [m.group(2).decode("utf-8", "ignore") for m in _asset_ref_re.finditer(raw)]
    inline_names = [m.group(1).decode("ascii") for m in _inline_scripts_re.finditer(raw)]
    with _cache_lock:
        _structure_cache[key] = (signature, refs, inline_names)
    return refs, inline_names


def _gzip_blob(key: str, signature: object, payload: bytes) -> bytes:
    cached = _gzip_cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    blob = gzip.compress(payload, 6)
    with _cache_lock:
        _gzip_cache[key] = (signature, blob)
    return blob


def _file_response(target, *, request=None, inject_versions=False, cache_control=None):
    """Serve a static file with sane caching and on-the-fly gzip.

    ``GZipMiddleware`` deliberately skips streaming responses, and
    ``FileResponse`` is one — so a plain ``FileResponse`` means every CSS/JS
    asset is shipped uncompressed. Compressing here keeps the streaming shape
    while actually sending compressed bytes.
    """
    content_type, _ = mimetypes.guess_type(str(target))
    content_type = content_type or "application/octet-stream"
    suffix = target.suffix.lower()
    signature = _signature(target)
    size = signature[0]

    accept_gzip = request is None or "gzip" in (
        request.META.get("HTTP_ACCEPT_ENCODING") or ""
    ).lower()
    compress = accept_gzip and suffix in COMPRESSIBLE_SUFFIXES and size <= INLINE_MAX_BYTES

    etag = 'W/"%x-%x-%s"' % (size, signature[1], "gz" if compress else "id")
    if cache_control is None:
        if suffix == ".html":
            # 每次都要校验新鲜度，但允许浏览器先用缓存副本绘制，避免导航卡在往返上。
            # SWR 窗口要短：它意味着"最多给你看 N 秒前的旧页面"。86400 会导致改完
            # 样式后第一次打开仍是旧内容，第二次刷新才更新。开发态直接关掉。
            cache_control = (
                "no-cache"
                if settings.DEBUG
                else "max-age=0, must-revalidate, stale-while-revalidate=30"
            )
        else:
            cache_control = "public, max-age=31536000, immutable"

    # Unchanged asset: 304 without ever reading the payload.
    if request is not None and request.META.get("HTTP_IF_NONE_MATCH") == etag:
        response = HttpResponseNotModified()
    elif size > INLINE_MAX_BYTES:
        # Large binaries (video, release packages) stream straight from disk.
        response = FileResponse(target.open("rb"), content_type=content_type)
    else:
        payload = (
            _rendered_html(target, signature)
            if inject_versions
            else target.read_bytes()
        )
        if compress:
            # 渲染出来的 HTML 不只取决于这个文件本身：它还带着被引用资源的
            # ?v=<hash> 与内联脚本的内容。只按文件自身 mtime 缓存 gzip 结果，
            # 会让「旧 HTML + 旧 ?v=」被钉死在所有支持 gzip 的客户端上 ——
            # 改了 CSS 之后页面仍然引用旧版本号，而旧版本是 immutable 缓存的，
            # 于是样式永远不更新。这里改用渲染结果的内容摘要做签名。
            gzip_signature = (
                hashlib.sha256(payload).hexdigest() if inject_versions else signature
            )
            payload = _gzip_blob(str(target), gzip_signature, payload)
            response = FileResponse(io.BytesIO(payload), content_type=content_type)
            response["Content-Encoding"] = "gzip"
        else:
            response = FileResponse(io.BytesIO(payload), content_type=content_type)
        response["Content-Length"] = str(len(payload))

    response["ETag"] = etag
    response["Cache-Control"] = cache_control
    response["Vary"] = "Accept-Encoding"
    return response


@require_GET
def legacy_admin_redirect(request):
    return redirect("/login?next=/admin")


@ensure_csrf_cookie
@require_GET
def page(request, page_path="", **kwargs):
    if page_path == "admin" or page_path.startswith("admin/"):
        if not get_admin_context(request):
            return redirect(f"/login?next=/{page_path}")
    relative = PAGE_MAP.get(page_path)
    if relative is None:
        raise Http404
    return _file_response(_safe_static_path(relative), request=request, inject_versions=True)


@ensure_csrf_cookie
@require_GET
def product_page(request, slug):
    return _file_response(_safe_static_path("product.html"), request=request, inject_versions=True)


@ensure_csrf_cookie
@require_GET
def tutorial_page(request, slug):
    return _file_response(_safe_static_path("tutorial-detail.html"), request=request, inject_versions=True)


@ensure_csrf_cookie
@require_GET
def external_project_page(request, project_id):
    return _file_response(_safe_static_path("external-project.html"), request=request, inject_versions=True)


@ensure_csrf_cookie
@require_GET
def glossary_page(request, slug):
    return _file_response(_safe_static_path("glossary-detail.html"), request=request, inject_versions=True)


@require_GET
def static_asset(request, asset_path):
    return _file_response(_safe_static_path(asset_path), request=request)


@require_GET
def material_file(request, asset_path):
    root = Path(settings.MATERIAL_ROOT).resolve()
    target = (root / asset_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return HttpResponseForbidden()
    if not target.is_file():
        raise Http404
    return _file_response(target, request=request)


def _safe_media_path(relative):
    """Resolve /uploads/<path> inside MEDIA_ROOT.

    上传目录里既有公开图片，也有付费发布包和分片上传的临时目录，所以这里
    比静态目录严格：只允许图片/视频后缀，并且拒绝任何以点开头的路径段
    （.chunk-sessions 这类中间产物不该被直接下载）。
    """
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / relative).resolve()
    try:
        relative_parts = target.relative_to(root).parts
    except ValueError:
        raise Http404 from None
    if not relative_parts:
        raise Http404
    if any(part.startswith(".") for part in relative_parts):
        raise Http404
    if target.suffix.lower() not in MEDIA_SERVED_SUFFIXES:
        raise Http404
    if not target.is_file():
        raise Http404
    return target


@require_GET
def media_file(request, asset_path):
    target = _safe_media_path(asset_path)
    # 上传物不像构建产物那样带内容哈希，改头像时可能覆盖同名文件，所以用
    # 有限的 max-age 而不是 immutable：绝大多数命中直接进缓存，改名/覆盖后
    # 最多陈旧一个缓存周期，且 ETag 让回源校验只花一个 304。
    seconds = max(0, int(getattr(settings, "MEDIA_CACHE_SECONDS", 604800)))
    response = _file_response(
        target,
        request=request,
        cache_control=f"public, max-age={seconds}, stale-while-revalidate=86400",
    )
    if target.suffix.lower() == ".svg":
        # SVG 是脚本宿主：内联 <script> 会在图片上下文之外执行，必须锁死。
        response["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        )
        response["X-Content-Type-Options"] = "nosniff"
    return response
