"""发帖 / 编辑话题的编辑器样式必须出现在论坛页真正加载的产物里。

踩过一次坑：远端 PR 把 `.article-editor` 那一整套样式写进了 `static/forum.css`，
而论坛页在 CSS 构建化之后只加载 `forum.tailwind.css`（由 `static/src/forum.css`
构建）。样式落在一个没人引用的文件里，编辑器就退化成裸 HTML —— 没有边框、
两栏竖着堆在一起、模式按钮变成几行纯文字。

这三个断言分别钉住：页面加载哪个文件、产物里有没有编辑器样式、源文件是不是唯一
真相（直接改产物会在下次 build 时被冲掉）。
"""

from pathlib import Path

from django.conf import settings
from django.test import TestCase


class ArticleEditorStyleTests(TestCase):
    @staticmethod
    def _read(*parts: str) -> str:
        path = Path(settings.BASE_DIR).joinpath(*parts)
        return path.read_text(encoding="utf-8", errors="ignore")

    def test_forum_page_loads_the_built_bundle(self):
        html = self._read("static", "forum.html")
        self.assertIn("/forum.tailwind.css", html)
        # 旧样式表已经不被论坛页引用，往里加样式等于没加。
        self.assertNotIn('href="/forum.css"', html)

    def test_built_bundle_contains_editor_styles(self):
        built = self._read("static", "forum.tailwind.css")
        for token in (
            ".article-editor{",
            ".article-editor-panes",
            ".article-editor-toolbar",
            ".article-editor-status",
            ".article-format-bar",
            ".article-pane-heading",
        ):
            with self.subTest(token=token):
                self.assertIn(token, built)

    def test_editor_styles_live_in_the_src_source(self):
        source = self._read("static", "src", "forum.css")
        for token in (".article-editor {", "@container article-editor", ".modal-new-topic {"):
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_editor_modal_is_wide_enough_for_two_panes(self):
        source = self._read("static", "src", "forum.css")
        # 600px 的双栏每边不到 300px，正文会被挤成一条。
        self.assertIn("min(1180px, 94vw)", source)
