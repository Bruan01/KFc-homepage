# pyright: reportMissingImports=false
"""论坛列表分页的接线测试。

每页 10 条 + 页码分页器这套约定散落在三个地方（HTML 容器、JS 逻辑、CSS 样式），
任一处被改回去都不会报错，只会变成「两份翻页入口」或「样式丢失」，所以用测试钉住。
"""
from pathlib import Path

from django.conf import settings
from django.test import TestCase


class ForumPagerWiringTests(TestCase):
    """「加载更多」已经移除：#loadMore 一旦重新出现就会和分页器并存。"""

    @staticmethod
    def _static_dir() -> Path:
        return Path(settings.BASE_DIR) / "static"

    def test_forum_page_has_pager_and_no_load_more(self):
        static = self._static_dir()
        html = (static / "forum.html").read_text(encoding="utf-8")
        self.assertIn('id="topicPager"', html)
        self.assertNotIn("loadMore", html)

    def test_forum_js_requests_ten_per_page_and_renders_pager(self):
        static = self._static_dir()
        script = (static / "forum.js").read_text(encoding="utf-8")
        self.assertIn("pageSize: 10", script)
        self.assertNotIn("loadMore", script)
        for token in ("renderPager", "goToPage", "pageNumbers", "totalPages"):
            with self.subTest(token=token):
                self.assertIn(token, script)

    def test_pager_styles_are_present_in_built_css(self):
        static = self._static_dir()
        built = (static / "forum.tailwind.css").read_text(encoding="utf-8", errors="ignore")
        for token in ("topic-pager", "pager-btn-active", "pager-summary"):
            with self.subTest(token=token):
                self.assertIn(token, built)

    def test_pager_source_of_truth_is_the_src_bundle(self):
        """分页样式必须写在 static/src/forum.css 里，否则下次构建会被冲掉。"""
        static = self._static_dir()
        source = (static / "src" / "forum.css").read_text(encoding="utf-8")
        self.assertIn(".topic-pager", source)
