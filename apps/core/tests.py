# pyright: reportMissingImports=false

import gzip as gzip_lib
import json
import re
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.test import RequestFactory
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone

from apps.core import pages
from apps.accounts.models import LegacySession
from apps.downloads.models import UploadSession


class NewAPIProxyTests(TestCase):
    @patch("apps.core.views._newapi_get")
    def test_status_filters_sensitive_fields(self, fetch):
        fetch.return_value = (
            {
                "success": True,
                "data": {
                    "system_name": "Status",
                    "version": "v1",
                    "server_address": "http://internal.example:8579",
                    "announcements": [
                        {"type": "info", "content": "访问 http://10.0.0.1:9000"}
                    ],
                },
            },
            200,
        )

        response = self.client.get("/api/newapi/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("server_address", body["data"])
        self.assertEqual(body["data"]["announcements"][0]["content"], "访问 [地址已隐藏]")
        self.assertNotIn("10.0.0.1", response.content.decode())

    @patch("apps.core.views._newapi_get")
    def test_models_and_channels_return_public_fields_only(self, fetch):
        def response_for(path):
            if path == "/api/models":
                return {"success": True, "data": {"1": ["gpt-test"]}}, 200
            return {
                "success": True,
                "data": {
                    "items": [
                        {
                            "id": 1,
                            "name": "Channel",
                            "status": 1,
                            "models": "gpt-test,claude-test",
                            "base_url": "http://internal.example",
                            "key": "secret",
                        }
                    ]
                },
            }, 200

        fetch.side_effect = response_for

        models = self.client.get("/api/newapi/models")
        channels = self.client.get("/api/newapi/channels")

        self.assertEqual(models.json()["data"], {"models": [{"name": "gpt-test"}], "total": 1})
        channel = channels.json()["data"]["channels"][0]
        self.assertEqual(channel["model_count"], 2)
        self.assertNotIn("base_url", channel)
        self.assertNotIn("key", channel)



    def test_health_returns_json(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("time", response.json())

    def test_health_rejects_post(self):
        response = self.client.post("/api/health")
        self.assertEqual(response.status_code, 405)


class ForumPageTests(TestCase):
    def test_forum_page_is_public_and_seeds_csrf(self):
        response = self.client.get("/forum")

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("KFlow Community", body)
        self.assertIn('/forum.css', body)
        self.assertIn('/forum.js', body)
        self.assertIn("csrftoken", self.client.cookies)


class NewTopicButtonWiringTests(TestCase):
    """「发帖晒作品 / 发帖」按钮必须真的接线。

    首页的 #newTopicBtn 曾经是完全没有事件绑定的：绑定代码在 forum.js 里，而首页
    只加载 community.js —— 按钮点了不报错、不跳转，就是一个死按钮，而且不会留下
    任何控制台线索。这里扫全部静态页，凡是文案里带「发帖」或属性里带 compose 的
    按钮，必须至少有一条通路：onclick / href / 或 id 在某个脚本里被引用。
    """

    @staticmethod
    def _static_dir() -> Path:
        return Path(settings.BASE_DIR) / "static"

    def test_every_compose_button_has_a_handler(self):
        static = self._static_dir()
        scripts = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in sorted(static.glob("*.js"))
        )
        tag_re = re.compile(r"<(?:button|a)\b([^>]*)>([^<]{0,40})", re.S)
        id_re = re.compile(r'id="([^"]+)"')
        checked = 0
        for html in sorted(static.glob("*.html")):
            text = html.read_text(encoding="utf-8", errors="ignore")
            for match in tag_re.finditer(text):
                attrs, label = match.group(1), match.group(2)
                if "发帖" not in label and "compose" not in attrs:
                    continue
                checked += 1
                id_match = id_re.search(attrs)
                wired = (
                    "onclick=" in attrs
                    or "href=" in attrs
                    or bool(id_match and id_match.group(1) in scripts)
                )
                self.assertTrue(
                    wired,
                    f"{html.name} 里的发帖按钮没有接线：{attrs.strip()[:90]}",
                )
        # 扫得太少说明匹配规则失效了，宁可报错也不要静默通过
        self.assertGreaterEqual(checked, 5)

    def test_homepage_loads_the_script_that_binds_the_button(self):
        """首页只加载 community.js，绑定必须落在它里面（forum.js 不在首页）。"""
        static = self._static_dir()
        index = (static / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="newTopicBtn"', index)
        self.assertIn("/community.js", index)
        self.assertNotIn("/forum.js", index)
        community = (static / "community.js").read_text(encoding="utf-8")
        self.assertIn("newTopicBtn", community)


class ImmersiveReadingWiringTests(TestCase):
    """沉浸式阅读必须真的被加载，且样式表顺序正确。

    CSS 层叠是这套功能最脆的地方：主题里有一批 "!important + 高特异性" 的卡片规则，
    沉浸样式的选择器必须堆到同等或更高特异性才压得住；而顺序上 immersive.css 必须
    排在 comic-style.css 之后（同特异性时后者胜）。这两点都靠约定，所以用测试钉住。
    """

    PAGES = [
        "tutorials.html",
        "tutorial-detail.html",
        "glossary.html",
        "glossary-detail.html",
        "forum.html",
        "guide.html",
    ]

    def test_content_pages_load_immersive_assets(self):
        static = Path(settings.BASE_DIR) / "static"
        self.assertTrue((static / "immersive.css").is_file())
        self.assertTrue((static / "immersive.js").is_file())
        for name in self.PAGES:
            html = (static / name).read_text(encoding="utf-8")
            with self.subTest(page=name):
                self.assertIn("/immersive.css", html)
                self.assertIn("/immersive.js", html)
                self.assertNotEqual(
                    html.index("/immersive.css"),
                    -1,
                    f"{name} 没有加载沉浸阅读样式表",
                )

    def test_immersive_css_loads_after_theme_overrides(self):
        """顺序错位会让阅读底色被主题的 !important 规则刷掉。"""
        static = Path(settings.BASE_DIR) / "static"
        for name in self.PAGES:
            html = (static / name).read_text(encoding="utf-8")
            with self.subTest(page=name):
                self.assertGreater(
                    html.index("/immersive.css"),
                    html.index("/comic-style.css"),
                    f"{name} 里 immersive.css 必须在 comic-style.css 之后",
                )

    def test_js_exposes_the_public_api_and_reuses_tutorial_button(self):
        static = Path(settings.BASE_DIR) / "static"
        js = (static / "immersive.js").read_text(encoding="utf-8")
        for token in ("window.kflowImmersive", "toggle", "enter", "exit"):
            self.assertIn(token, js)
        learn = (static / "learn.js").read_text(encoding="utf-8")
        self.assertIn("window.kflowImmersive", learn, "教程页按钮必须转交给通用沉浸模块")


class GuidePageTests(TestCase):
    def test_guide_page_is_public_and_excludes_admin_entrypoints(self):
        response = self.client.get("/guide")

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("第一次来到 KFlow", body)
        self.assertIn('data-guide-step="service"', body)
        self.assertIn('href="/guide"', body)
        self.assertNotIn("/admin", body)


class StaticPageRenderCacheTests(TestCase):
    """页面渲染缓存必须跟随「被引用的资源」失效，尤其是内联脚本。

    内联脚本在 HTML 里被替换成代码块之后就再也扫不到了 —— 曾经在改写后的文本上
    收集签名，导致 theme.js 的改动永远不会让缓存 key 变化：改了主题脚本，页面却
    一直发旧版，除非重启进程。
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        static = root / "static"
        static.mkdir()
        (static / "index.html").write_bytes(
            b'<html><head>\n<script src="/theme.js"></script>\n'
            b'<link rel="stylesheet" href="/site.css" />\n</head><body>hi</body></html>'
        )
        (static / "theme.js").write_bytes(b"/* theme v1 */\n")
        (static / "site.css").write_bytes(b"body { color: red; }\n")
        self.base_dir = root
        self.static = static

    def _render(self):
        with override_settings(BASE_DIR=self.base_dir):
            target = pages._safe_static_path("index.html")
            return pages._rendered_html(target, pages._signature(target))

    def test_repeated_render_is_cached(self):
        first = self._render()
        self.assertIn(b"theme v1", first)
        self.assertEqual(first, self._render())

    def test_inline_script_change_invalidates_cache(self):
        self._render()
        # 内容长度必须变化：签名是 (size, mtime)，同秒内只改内容不改长度会被 miss
        (self.static / "theme.js").write_bytes(b"/* theme v2 - longer payload */\n")
        rendered = self._render()
        self.assertIn(b"theme v2", rendered, "内联脚本改了，HTML 缓存却没有失效")
        self.assertNotIn(b"theme v1", rendered)

    def test_referenced_stylesheet_change_invalidates_cache(self):
        self._render()
        (self.static / "site.css").write_bytes(b"body { color: red; background: blue; }\n")
        rendered = self._render()
        self.assertIn(b'site.css?v=', rendered)

    def test_gzip_response_follows_referenced_asset_change(self):
        """gzip 分支也要跟随被引用资源失效。

        gzip 缓存曾经只按 HTML 自身的 (size, mtime) 做签名。改了 CSS 但没动 HTML
        时，支持 gzip 的客户端会一直拿到「旧 HTML + 旧 ?v=」——而旧版本号是
        immutable 缓存的，样式就再也更新不了。只有不发 Accept-Encoding: gzip 的
        客户端（例如 curl）能看到新版本，于是变成「我这里好了、用户那里没变」。
        """
        factory = RequestFactory()

        def body_with_gzip():
            with override_settings(BASE_DIR=self.base_dir):
                target = pages._safe_static_path("index.html")
                response = pages._file_response(
                    target,
                    request=factory.get("/", HTTP_ACCEPT_ENCODING="gzip"),
                    inject_versions=True,
                )
            return gzip_lib.decompress(b"".join(response.streaming_content))

        def version(html: bytes) -> bytes:
            match = re.search(rb"site\.css\?v=([0-9a-f]+)", html)
            self.assertIsNotNone(match, "HTML 里没有带版本号的样式表引用")
            return match.group(1)  # type: ignore[union-attr]

        first = version(body_with_gzip())
        (self.static / "site.css").write_bytes(
            b"body { color: red; background: blue; margin: 0; }\n"
        )
        self.assertNotEqual(
            first,
            version(body_with_gzip()),
            "改了被引用的 CSS，gzip 客户端拿到的 ?v= 却没有变化",
        )

    def test_conditional_html_revalidates_when_only_dependencies_change(self):
        """A cached HTML response must not retain an obsolete immutable script."""
        target = self.static / "index.html"
        target.write_bytes(target.read_bytes().replace(b"</head>", b'<script src="/murmurs.js"></script></head>'))
        (self.static / "murmurs.js").write_bytes(b"/* menu v1 */")
        factory = RequestFactory()
        for encoding in ["identity", "gzip"]:
            for dependency in ["murmurs.js", "site.css", "theme.js"]:
                with self.subTest(encoding=encoding, dependency=dependency), override_settings(BASE_DIR=self.base_dir):
                    def request(etag=None):
                        headers = {"HTTP_ACCEPT_ENCODING": encoding}
                        if etag:
                            headers["HTTP_IF_NONE_MATCH"] = etag
                        return pages._file_response(target, request=factory.get("/", **headers), inject_versions=True)

                    initial = request()
                    old_etag = initial["ETag"]
                    initial.close()
                    unchanged = request(old_etag)
                    self.assertEqual(unchanged.status_code, 304)
                    dep = self.static / dependency
                    dep.write_bytes(dep.read_bytes() + b"\n/* changed dependency */")
                    refreshed = request(old_etag)
                    self.assertEqual(refreshed.status_code, 200)
                    self.assertNotEqual(refreshed["ETag"], old_etag)
                    body = b"".join(refreshed.streaming_content)
                    if encoding == "gzip":
                        body = gzip_lib.decompress(body)
                    if dependency == "theme.js":
                        self.assertIn(b"changed dependency", body)
                    else:
                        self.assertIn(f'{dependency}?v={pages.asset_version(dependency)}'.encode(), body)
                    refreshed.close()


class CSRFFlowTests(TestCase):
    def test_static_page_seeds_csrf_and_write_requires_matching_token(self):
        client = Client(enforce_csrf_checks=True)
        page = client.get("/login")
        self.assertEqual(page.status_code, 200)
        page_body = b"".join(page.streaming_content).decode("utf-8")
        self.assertIn("/csrf.js", page_body)
        self.assertIn("csrftoken", client.cookies)
        csrf = client.cookies["csrftoken"].value

        blocked = client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "admin123"}),
            content_type="application/json",
        )
        self.assertEqual(blocked.status_code, 403)

        allowed = client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "admin123"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(allowed.status_code, 200)


class MaintenanceCommandTests(TestCase):
    def test_cleanup_sessions_removes_expired_django_and_legacy_rows(self):
        from django.contrib.sessions.models import Session

        Session.objects.create(
            session_key="expired-django",
            session_data="e30=",
            expire_date=timezone.now() - timedelta(minutes=1),
        )
        LegacySession.objects.create(
            token="expired-legacy",
            role="user",
            username="expired",
            exp=timezone.now().timestamp() - 60,
            created_at="x",
            updated_at="x",
        )
        output = StringIO()
        call_command("cleanup_sessions", stdout=output)
        self.assertEqual(Session.objects.filter(session_key="expired-django").count(), 0)
        self.assertEqual(LegacySession.objects.filter(token="expired-legacy").count(), 0)
        self.assertIn("Removed", output.getvalue())

    def test_cleanup_upload_sessions_removes_expired_persistent_row(self):
        UploadSession.objects.create(
            upload_id="expired-upload",
            product_id=1,
            username="admin",
            level=3,
            original="archive.zip",
            size=1,
            count=1,
            platform="macOS",
            architecture="ARM64",
            expires_at=timezone.now().timestamp() - 60,
            created_at="x",
        )
        call_command("cleanup_upload_sessions", stdout=StringIO())
        self.assertFalse(UploadSession.objects.filter(upload_id="expired-upload").exists())
