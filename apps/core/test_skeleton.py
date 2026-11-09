# pyright: reportMissingImports=false
"""全站首屏骨架屏的接线契约。

骨架屏必须在任何外链 CSS/JS 到达前就显示，所以三个片段全部由
apps/core/pages.py 内联到 HTML，页面源码里看不到它们 —— 这也意味着
缓存 key、变体分发、兜底逻辑都得靠测试钉住，否则改了样式不生效、
或者某个资源失败就把内容永久盖住。
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from . import pages


SKELETON_PAGES = sorted(set(pages.PAGE_MAP.values()))


class SkeletonRenderingTests(TestCase):
    def setUp(self):
        # 渲染结果是进程级缓存，测试之间先清掉，避免互相串味。
        pages._html_cache.clear()

    def render(self, filename):
        target = pages._safe_static_path(filename)
        return pages._rendered_html(target, pages._signature(target)).decode("utf-8")

    def test_every_static_page_gets_an_inline_skeleton(self):
        for filename in SKELETON_PAGES:
            with self.subTest(page=filename):
                html = self.render(filename)
                self.assertIn('<style id="kflowSkeletonStyles" data-kflow-skeleton>', html)
                self.assertIn('id="kflowSkeleton"', html)
                self.assertIn('/* /skeleton.js */', html)
                self.assertIn("window.kflowSkeleton", html)
                self.assertIn("<noscript>", html)
                # 样式必须先于页面自己的外链 CSS，否则首屏仍会先白一下。
                style_at = html.index('id="kflowSkeletonStyles"')
                first_css = html.find('rel="stylesheet"')
                if first_css != -1:
                    self.assertLess(style_at, first_css)
                # 骨架 DOM 紧跟 <body>，控制脚本不依赖 defer/external 资源。
                self.assertLess(html.index('id="kflowSkeleton"'), html.index("/* /skeleton.js */"))

    def test_skeleton_has_zero_external_dependencies(self):
        css = self.source("skeleton.css")
        js = self.source("skeleton.js")
        fragment = self.source("skeleton.html")
        for text in (css, js, fragment):
            for banned in ("http://", "https://", "@import", "fonts.googleapis", "<script src", "<link"):
                with self.subTest(banned=banned):
                    self.assertNotIn(banned, text)
        self.assertNotIn('<script src="/skeleton.js"', self.render("index.html"))

    def source(self, filename):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / "static" / filename).read_text(encoding="utf-8")

    def test_skeleton_uses_neutral_tags(self):
        """骨架是 body 第一个元素，绝不能用语义标签。

        实测踩过：片段里写了 <header> 后，theme.js 的
        document.querySelector("header") 会把主题切换按钮插进骨架，
        骨架移除时按钮被一起删掉；nav/section/article 同理会劫持
        依赖 querySelector 的站点脚本。
        """
        fragment = self.source("skeleton.html")
        self.assertNotRegex(
            fragment,
            r"<(?:header|nav|aside|section|article|main|form|button|footer|a)\b",
        )
        self.assertIn('role="status"', fragment)
        self.assertIn("__KFLOW_SKELETON_VARIANT__", fragment)

    def test_variants_are_dispatched_by_page_type(self):
        expected = {
            "user-login.html": "auth",
            "admin.html": "admin",
            "admin-bigscreen.html": "admin",
            "tutorial-detail.html": "article",
            "glossary-detail.html": "article",
            "forum-profile.html": "article",
            "lrobotcup.html": "article",
            "forum.html": "default",
            "products.html": "default",
        }
        for filename, variant in expected.items():
            with self.subTest(page=filename):
                self.assertIn('data-skeleton="%s"' % variant, self.render(filename))

    def test_hide_logic_has_load_hook_timeout_and_noscript_fallback(self):
        js = self.source("skeleton.js")
        for snippet in ('window.addEventListener("load"', "MAX_VISIBLE_MS",
                        "window.setTimeout(finish, MAX_VISIBLE_MS)",
                        "prefers-reduced-motion", "ready: finish", "hide: finish",
                        'getElementById("kflowSkeletonStyles")'):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, js)
        html = self.render("index.html")
        self.assertIn("#kflowSkeleton{display:none!important}", html)
        css = self.source("skeleton.css")
        self.assertIn('html[data-theme="comic"]', css)
        self.assertIn('html[data-theme="vibrancy"]', css)
        self.assertIn("#kflowSkeleton[data-state=\"hidden\"]", css)
        # 毛玻璃主题全局禁装饰动画，骨架必须显式退化为静态色块。
        self.assertIn('html[data-theme="vibrancy"] #kflowSkeleton .kf-sk-shimmer', css)
        self.assertIn("#kflowSkeleton .kf-sk-shimmer", css)

    def test_skeleton_asset_changes_invalidate_render_cache(self):
        """片段不在页面源码里，缓存 key 必须显式带上它的内容摘要。"""
        target = pages._safe_static_path("index.html")
        signature = pages._signature(target)
        real = pages._skeleton_bundle()
        first = pages._rendered_html(target, signature)

        altered = (real[0], real[1], b"#kflowSkeleton{background:#123456!important}\n",
                   real[3], "altered-css")
        with patch.object(pages, "_skeleton_bundle", return_value=altered):
            second = pages._rendered_html(target, signature)
        self.assertIn(b"background:#123456", second)

        with patch.object(pages, "_skeleton_bundle", return_value=real):
            third = pages._rendered_html(target, signature)
        self.assertEqual(first, third, "恢复原片段后必须重新拿到原始渲染结果")

    @override_settings(HTTPS_REQUIRED=True)
    def test_https_guard_still_runs_before_skeleton_and_csrf(self):
        html = self.render("user-login.html")
        self.assertLess(html.index("data-kflow-https"), html.index("kflowSkeletonStyles"))
        self.assertLess(html.index("data-kflow-https"), html.index("/* /csrf.js */"))


class SkeletonDegradedRenderingTests(SimpleTestCase):
    """裁剪过的 static 目录没有骨架片段时，页面必须照常渲染。"""

    def test_missing_skeleton_assets_do_not_break_html_rendering(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        static = root / "static"
        static.mkdir()
        (static / "index.html").write_bytes(
            b'<html><head><link rel="stylesheet" href="/site.css" /></head>'
            b"<body>ok</body></html>"
        )
        (static / "site.css").write_bytes(b"body { color: red; }\n")
        with override_settings(BASE_DIR=root):
            target = pages._safe_static_path("index.html")
            html = pages._rendered_html(target, pages._signature(target))
            self.assertEqual(pages.skeleton_head_html(), "")
            self.assertEqual(pages.skeleton_body_html("default"), "")
        self.assertIn(b"site.css?v=", html)
        self.assertNotIn(b"kflowSkeleton", html)


class SkeletonResponseTests(TestCase):
    def test_public_routes_serve_the_skeleton(self):
        routes = (
            "/", "/login", "/forum", "/forum/lrobotcup", "/lrobotcup",
            "/products", "/murmurs", "/tutorials", "/personality", "/imaging",
            "/glossary/anything", "/tutorials/anything", "/product/anything",
        )
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200, route)
                payload = (
                    b"".join(response.streaming_content)
                    if response.streaming
                    else response.content
                ).decode("utf-8")
                self.assertIn('id="kflowSkeleton"', payload)
                self.assertIn("window.kflowSkeleton", payload)
