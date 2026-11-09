# pyright: reportMissingImports=false
"""LRobotcup（具身智能入行专题）静态页的接线契约。

这个页面没有服务端模板：一个 static/*.html + PAGE_MAP + 显式 URL。任何一处
漏接都会让页面「能打开但不好用」（主题错乱、样式拿到旧版本号、发帖按钮
没有接线），所以用测试把约定钉住。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from . import pages


class LRobotcupPageTests(TestCase):
    def html(self, url="/forum/lrobotcup"):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        payload = (
            b"".join(response.streaming_content)
            if response.streaming
            else response.content
        )
        return payload.decode("utf-8")

    def source(self, filename):
        return (Path(settings.BASE_DIR) / "static" / filename).read_text(encoding="utf-8")

    def test_both_urls_serve_the_topic_page(self):
        self.assertEqual(pages.PAGE_MAP["forum/lrobotcup"], "lrobotcup.html")
        self.assertEqual(pages.PAGE_MAP["lrobotcup"], "lrobotcup.html")
        for url in ("/forum/lrobotcup", "/lrobotcup"):
            with self.subTest(url=url):
                html = self.html(url)
                self.assertIn("LRobotcup", html)
                self.assertIn("具身智能", html)
                self.assertIn("学习路线", html)
                self.assertIn("交流贴", html)

    def test_local_assets_are_versioned_and_blocking_scripts_inlined(self):
        html = self.html()
        # ?v=<sha256[:12]> 由 pages.py 注入；漏了就会拿到 immutable 的旧样式。
        self.assertRegex(html, r"/lrobotcup\.css\?v=[0-9a-f]{12}")
        self.assertRegex(html, r"/lrobotcup\.js\?v=[0-9a-f]{12}")
        # 调研数据独立成文件，改数据后也必须能顶掉 immutable 缓存。
        self.assertRegex(html, r"/lrobotcup-data\.js\?v=[0-9a-f]{12}")
        for script in ("theme.js", "csrf.js", "icons.js"):
            self.assertIn("/* /%s */" % script, html)

    def test_theme_stack_order_and_toggle(self):
        raw = self.source("lrobotcup.html")
        stack = [
            "/theme.js",
            "/glass-theme.css",
            "/macos-vibrancy.css",
            "/comic-style.css",
            "/immersive.css",
            "/mobile.css",
            "/lrobotcup.css",
        ]
        positions = [raw.index(asset) for asset in stack]
        self.assertEqual(positions, sorted(positions), "主题 CSS 顺序被打乱")
        self.assertIn("data-theme-toggle", raw)
        self.assertNotIn("data-theme=\"", raw, "不要手写 data-theme，交给 theme.js")
        self.assertIn("<head>", raw, "HTTPS guard 依赖 <head> 标签注入")
        self.assertIn('data-im-article', raw)

    def test_all_content_sections_exist(self):
        raw = self.source("lrobotcup.html")
        for anchor in (
            "start", "tracks", "research", "roadmap", "stack", "projects",
            "resources", "hardware", "news", "community", "discuss", "sources",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn('id="%s"' % anchor, raw)

    def test_left_sidebar_router_is_wired(self):
        """12 个板块必须能靠左侧栏单独路由打开，而不是叠成一条超长页。"""
        raw = self.source("lrobotcup.html")
        css = self.source("lrobotcup.css")
        js = self.source("lrobotcup.js")
        self.assertIn('id="lrcLayout"', raw)
        self.assertIn('class="lrc-sidebar"', raw)
        for marker in ("lrcSidebar", "lrcAllToggle", "lrcRouteHint",
                       "lrcPrevRoute", "lrcNextRoute", "lrcProgress"):
            with self.subTest(marker=marker):
                self.assertIn('id="%s"' % marker, raw)
        routes = (
            "start", "tracks", "research", "roadmap", "stack", "projects",
            "resources", "hardware", "news", "community", "discuss", "sources",
        )
        for route in routes:
            with self.subTest(route=route):
                self.assertIn('data-route="%s" href="#%s"' % (route, route), raw)
        self.assertEqual(raw.count('data-route="'), len(routes))
        # 侧栏固定、单板块视图、通读模式、上一/下一板块都要有实现。
        for snippet in (".lrc-layout", "position: sticky", ".lrc-article > section[hidden]",
                        "body.lrc-allmode", "@media (max-width: 900px)", "lrc-sidebar"):
            with self.subTest(css=snippet):
                self.assertIn(snippet, css)
        for snippet in ("function initRouter(", "history.pushState", "history.replaceState",
                        '"popstate"', '"hashchange"', ".lrc-article > section.lrc-section",
                        "goToRoute(\"community\")", "initRouter();"):
            with self.subTest(js=snippet):
                self.assertIn(snippet, js)
        # 首屏不能补写默认 hash：Chrome 会在 load 后按 fragment 把
        # section#start 顶到视口，hero 会被整个跳过（实测 scrollY 676）。
        # 后退回到无 hash 的那一帧则必须显式回顶。
        self.assertNotRegex(js, r"if \(!location\.hash\)\s*\{\s*history\.replaceState")
        self.assertIn("history.scrollRestoration", js)
        self.assertIn("if (!location.hash) window.scrollTo", js)
        # 旧横向 subnav 已退役，避免两套导航逻辑并存。
        self.assertNotIn('class="lrc-subnav"', raw)

    def test_lrobotcup_is_listed_as_a_product(self):
        """专题归入产品体系：头部产品下拉 + 产品站专题板块。"""
        header = self.source("header.js")
        products = self.source("products.html")
        for snippet in ("ensureLRobotcupInProducts", 'a[href="/products"]',
                        ".community-nav .nav-group", 'nav[aria-label="站点导航"] details',
                        "lrc-product-cta"):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, header if snippet != "lrc-product-cta" else products)
        # 必须先收进产品组并清掉旧顶级项，兜底函数才不会又加回一个重复入口。
        self.assertLess(header.index("ensureLRobotcupInProducts();"),
                        header.rindex("ensureLRobotcupLink();"))
        # 专题是可在线使用的板块，不进可下载产品网格（没有安装包，点进去会 404）。
        self.assertLess(products.index('id="productGrid"'), products.index('id="lrobotcup"'))
        self.assertIn("html[data-theme] body .container .panel .product-card", products)
        rendered = self.html("/products")
        self.assertIn('id="lrobotcup"', rendered)
        self.assertIn('href="/forum/lrobotcup"', rendered)
        # 专题页自己也要用站点标准导航：产品下拉组由 header.js 注入，
        # 不能残留一个孤立的顶级 LRobotcup 入口，否则从专题页看不到产品体系。
        page = self.source("lrobotcup.html")
        self.assertIn('class="nav-group-btn">产品', page)
        self.assertIn('href="/products"', page)
        self.assertNotIn('data-nav="lrobotcup"', page)
        # 短别名 /lrobotcup 也要点亮产品组，高亮逻辑用规范路径比对。
        self.assertIn('if (path === "/lrobotcup") path = "/forum/lrobotcup";', header)

    def test_compose_buttons_are_wired(self):
        raw = self.source("lrobotcup.html")
        # 全站约定：所有「发帖」入口统一跳 /forum?compose=1，且必须有接线。
        for match in re.finditer(r"<(?:button|a)\b([^>]*)>([^<]{0,40})", raw, re.S):
            attrs, label = match.group(1), match.group(2)
            if "发帖" not in label and "compose" not in attrs:
                continue
            self.assertTrue(
                "onclick=" in attrs or "href=" in attrs,
                "未接线的发帖入口: %s" % attrs,
            )
        self.assertIn("onclick=\"location.href='/forum?compose=1'\"", raw)

    def test_external_links_are_https_and_noreferrer(self):
        raw = self.source("lrobotcup.html")
        links = re.findall(r'href="(https?://[^"]+)"', raw)
        self.assertGreaterEqual(len(links), 8)
        for url in links:
            with self.subTest(url=url):
                self.assertTrue(url.startswith("https://"), url)
        for match in re.finditer(r'<a\b[^>]*href="https?://[^"]+"[^>]*>', raw):
            self.assertIn('rel="noopener noreferrer"', match.group(0))
            self.assertIn('target="_blank"', match.group(0))

    def test_entry_points_and_compose_seed_are_wired(self):
        header = self.source("header.js")
        self.assertIn("ensureLRobotcupLink()", header)
        self.assertIn('href="/forum/lrobotcup"', self.source("forum.html"))
        # 专题页自身不再硬编码自链接：入口由 header.js 注入「产品」下拉，
        # 页面只要加载了 header.js 且带产品组，导航就能把两者接起来。
        page = self.source("lrobotcup.html")
        self.assertIn('src="/header.js"', page)
        self.assertIn('class="nav-group-btn">产品', page)
        self.assertIn('href="/forum/lrobotcup"', header)
        self.assertIn("kflow:compose-seed", self.source("forum.js"))
        self.assertIn("applyComposeSeed()", self.source("forum.js"))
        self.assertIn("lrcCompose", self.source("lrobotcup.js"))

    def test_zero_base_onboarding_blocks_exist(self):
        raw = self.source("lrobotcup.html")
        # 小白第一次打开：先测起点、再看术语、最后知道学完能拿出什么。
        for marker in ("lrcQuizPy", "lrcQuizHw", "lrcQuizGoal", "lrcQuizResult",
                       "lrcGlossary", "lrcPortfolio", "lrcWeekList", "lrcSyncState",
                       "lrcNewsBriefCard", "lrcNewsBrief"):
            with self.subTest(marker=marker):
                self.assertIn('id="%s"' % marker, raw)
        self.assertIn("30 秒", raw)
        self.assertIn("就业", raw)

    def test_community_loop_is_wired_to_real_apis(self):
        """专题页必须真的读写社区，而不是又一个纯静态手册。"""
        js = self.source("lrobotcup.js")
        for endpoint in (
            "/api/learn/progress", "/api/learn/complete", "/api/learn/uncomplete",
            "/api/forum/topics", "/api/murmurs?channel=growth",
            "/api/feeds/items?source_category=embodied-ai",
            "/api/forum/topics/", "/forum?compose=1",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, js)
        self.assertIn("kflowAuthReady", js)
        self.assertIn('load({ tag: "具身智能" })', js)
        # 后端筛选参数确实存在，避免前端写了后端没实现。
        forum = (Path(settings.BASE_DIR) / "apps/forum/views.py").read_text(encoding="utf-8")
        murmurs = (Path(settings.BASE_DIR) / "apps/murmurs/views.py").read_text(encoding="utf-8")
        feeds = (Path(settings.BASE_DIR) / "apps/feeds/views.py").read_text(encoding="utf-8")
        self.assertIn('request.GET.get("tag"', forum)
        self.assertIn('request.GET.get("q")', murmurs)
        self.assertIn("source_category", feeds)
        learn_urls = (Path(settings.BASE_DIR) / "apps/learn/urls.py").read_text(encoding="utf-8")
        for path in ("api/learn/progress", "api/learn/uncomplete"):
            self.assertIn(path, learn_urls)

    def test_news_pipeline_is_server_scheduled(self):
        root = Path(settings.BASE_DIR)
        cron = (root / "scripts/setup_cron.sh").read_text(encoding="utf-8")
        self.assertIn("publish_lrobotcup_weekly", cron)
        self.assertGreaterEqual(cron.count("publish-lrobotcup-weekly"), 3, "cron 与 launchd 安装/卸载列表都要注册")
        for command in (
            "apps/feeds/management/commands/seed_lrobotcup_sources.py",
            "apps/feeds/management/commands/publish_lrobotcup_weekly.py",
            "apps/forum/management/commands/seed_lrobotcup.py",
        ):
            with self.subTest(command=command):
                self.assertTrue((root / command).is_file())

    def test_page_uses_no_external_fonts(self):
        # 大陆访问 fonts.googleapis.com 会白屏约 10 秒，全站禁止外部字体。
        raw = self.source("lrobotcup.html")
        self.assertNotIn("fonts.googleapis.com", raw)
        self.assertNotIn("fonts.gstatic.com", raw)
