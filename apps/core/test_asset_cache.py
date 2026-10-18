# pyright: reportMissingImports=false
"""静态资源与上传物的缓存 / 压缩契约。

页面一打开就要拉几十个 css/js/webp。只要其中任何一个响应没有缓存头，或
者带着 ``Vary: Cookie``（CsrfViewMiddleware 默认给所有响应都加），浏览器和
CDN 就得反复回源——这就是「卡」的来源。这些测试把头部契约钉死。
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from apps.forum.models import ForumImage


class StaticAssetHeaderTests(TestCase):
    def _get(self, url, **extra):
        return self.client.get(url, HTTP_ACCEPT_ENCODING="gzip", **extra)

    def test_css_is_immutable_and_carries_an_etag(self):
        response = self._get("/static/forum.tailwind.css?v=deadbeef")
        self.assertEqual(response.status_code, 200)
        self.assertIn("immutable", response["Cache-Control"])
        self.assertIn("max-age=31536000", response["Cache-Control"])
        self.assertTrue(response["ETag"])

    def test_vary_does_not_split_the_cache_on_cookie(self):
        """Vary: Cookie 会让每份 CSS 按 cookie 切成多份，共享缓存直接失效。"""
        for url in ("/static/forum.tailwind.css", "/static/theme.js"):
            response = self._get(url)
            vary = [item.strip().lower() for item in response.get("Vary", "").split(",")]
            self.assertNotIn("cookie", vary, f"{url} 的 Vary 里仍有 Cookie")
            self.assertIn("accept-encoding", vary)

    def test_conditional_request_returns_304_without_a_body(self):
        first = self._get("/static/forum.tailwind.css")
        etag = first["ETag"]
        second = self.client.get(
            "/static/forum.tailwind.css",
            HTTP_ACCEPT_ENCODING="gzip",
            HTTP_IF_NONE_MATCH=etag,
        )
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.content, b"")
        self.assertEqual(second["ETag"], etag)

    def test_text_assets_are_gzipped(self):
        raw = (Path(settings.BASE_DIR) / "static" / "forum.tailwind.css").stat().st_size
        response = self._get("/static/forum.tailwind.css")
        self.assertEqual(response["Content-Encoding"], "gzip")
        payload = b"".join(response.streaming_content)
        self.assertLess(len(payload), raw // 2)

    def test_static_requests_never_touch_the_database(self):
        """静态请求带着本站 cookie 出门，不该因此触发 legacy session 查询。"""
        self.client.cookies[settings.SESSION_COOKIE_NAME] = "definitely-not-a-real-token"
        with self.assertNumQueries(0):
            response = self._get("/static/theme.js")
        self.assertEqual(response.status_code, 200)

    def test_html_pages_still_set_the_csrf_cookie(self):
        """短路只针对资源文件，页面必须照常种 CSRF cookie。"""
        response = self._get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", self.client.cookies)

    def test_api_routes_are_not_short_circuited(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    @override_settings(STATIC_ASSET_SHORTCIRCUIT=False)
    def test_legacy_path_still_serves_assets(self):
        """关掉短路开关后资源仍可达，只是重新走完整中间件栈。"""
        response = self._get("/static/theme.js")
        self.assertEqual(response.status_code, 200)


class UploadedMediaTests(TestCase):
    """上传物要能被浏览器缓存，但不能把付费发布包顺手公开出去。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.media = self.root / "uploads"
        (self.media / "forum" / "2026" / "10").mkdir(parents=True)
        (self.media / ".chunk-sessions").mkdir()
        (self.media / "forum" / "2026" / "10" / "alice.webp").write_bytes(b"\x52\x49\x46\x46" + b"0" * 512)
        (self.media / "avatar.svg").write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        (self.media / "p2-release.zip").write_bytes(b"PK\x03\x04" + b"0" * 64)
        (self.media / ".chunk-sessions" / "part.webp").write_bytes(b"chunk")
        self.override = override_settings(MEDIA_ROOT=self.media, MEDIA_CACHE_SECONDS=604800)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_image_is_cached_but_not_immutable(self):
        response = self.client.get("/uploads/forum/2026/10/alice.webp")
        self.assertEqual(response.status_code, 200)
        control = response["Cache-Control"]
        self.assertIn("max-age=604800", control)
        self.assertNotIn("immutable", control)
        self.assertTrue(response["ETag"])

    def test_conditional_request_is_cheap(self):
        first = self.client.get("/uploads/forum/2026/10/alice.webp")
        second = self.client.get(
            "/uploads/forum/2026/10/alice.webp",
            HTTP_IF_NONE_MATCH=first["ETag"],
        )
        self.assertEqual(second.status_code, 304)

    def test_release_packages_are_not_served_from_the_public_path(self):
        """发布包只能走鉴权接口，目录直连必须 404。"""
        self.assertEqual(self.client.get("/uploads/p2-release.zip").status_code, 404)

    def test_chunk_sessions_and_traversal_are_unreachable(self):
        self.assertEqual(self.client.get("/uploads/.chunk-sessions/part.webp").status_code, 404)
        self.assertEqual(self.client.get("/uploads/../static/theme.js").status_code, 404)
        self.assertEqual(self.client.get("/uploads/forum/../../static/theme.js").status_code, 404)

    def test_svg_is_locked_down(self):
        response = self.client.get("/uploads/avatar.svg")
        self.assertEqual(response.status_code, 200)
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_unknown_path_404s(self):
        self.assertEqual(self.client.get("/uploads/nope.webp").status_code, 404)


class ForumImageHeaderTests(TestCase):
    """帖子图走 /api/forum/images/<id>，同样不该被 Vary: Cookie 拖住。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=Path(self.tmp) / "uploads")
        self.override.enable()
        row = ForumImage(
            uploader_username="alice",
            content_type="image/webp",
            file_size=8,
            width=1,
            height=1,
        )
        row.file.save("forum/2026/10/alice.webp", ContentFile(b"0" * 8), save=True)
        self.image_id = row.pk

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_served_image_is_cacheable_without_cookie_vary(self):
        response = self.client.get(f"/api/forum/images/{self.image_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("immutable", response["Cache-Control"])
        vary = [item.strip().lower() for item in response.get("Vary", "").split(",")]
        self.assertNotIn("cookie", vary)

    def test_json_responses_keep_their_cookie_vary(self):
        """正文随登录态变化的接口必须保留 Vary: Cookie，否则缓存会串号。"""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        vary = [item.strip().lower() for item in response.get("Vary", "").split(",")]
        self.assertIn("cookie", vary)
