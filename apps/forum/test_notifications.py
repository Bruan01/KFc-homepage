# pyright: reportMissingImports=false
"""论坛页通知面板：结构必须与 /account 一致，样式必须进构建产物。

两件事曾经/容易出错：
1. 论坛页用过 daisyUI 的 .dropdown 结构，和 /account 的 .notif-* 长得完全
   不一样——同一个通知面板在两个页面是两种观感。
2. .notif-* 的样式只写在旧样式表 static/forum.css 里，而论坛页加载的是
   static/forum.tailwind.css（源：static/src/_shared.css）。样式表没人引用，
   面板就退化成一堆裸 DOM。
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

STATIC = Path(settings.BASE_DIR) / "static"
FORUM_HTML = STATIC / "forum.html"
ACCOUNT_HTML = STATIC / "account.html"

REQUIRED_IDS = ("notifBell", "notifBadge", "notifPanel", "notifList", "notifMarkAll")
REQUIRED_CLASSES = (
    "notif-wrap",
    "notif-bell",
    "notif-badge",
    "notif-panel",
    "notif-panel-head",
    "notif-list",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ForumNotificationMarkupTests(SimpleTestCase):
    def setUp(self):
        self.html = _read(FORUM_HTML)

    def test_page_loads_the_notification_script(self):
        """脚本已经就位但 DOM 不存在时，notifications.js 会静默 return。"""
        self.assertIn('src="/notifications.js"', self.html)

    def test_bell_markup_matches_the_account_page(self):
        account = _read(ACCOUNT_HTML)
        for class_name in REQUIRED_CLASSES:
            self.assertIn(
                f'class="{class_name}"',
                self.html,
                f"论坛页缺少 .{class_name}（/account 有）",
            )
            self.assertIn(
                f'class="{class_name}"',
                account,
                f"/account 缺少 .{class_name}——两边结构漂移了",
            )

    def test_script_hooks_are_present(self):
        """notifications.js 只认 id，缺一个就整块不工作。"""
        for node_id in REQUIRED_IDS:
            self.assertIn(f'id="{node_id}"', self.html)

    def test_no_legacy_dropdown_shell_left_behind(self):
        """旧的 daisyUI .dropdown 外壳要拆干净，否则两套样式会叠在一起。"""
        block = re.search(r'id="notifBell".*?id="notifList"', self.html, re.S)
        self.assertIsNotNone(block)
        self.assertNotIn("dropdown", block.group(0))
        self.assertNotIn("badge-secondary", block.group(0))


class ForumNotificationStyleTests(SimpleTestCase):
    def test_bundle_ships_the_component(self):
        """样式必须出现在论坛页真正加载的那份构建产物里。"""
        bundle = _read(STATIC / "forum.tailwind.css")
        for class_name in REQUIRED_CLASSES:
            self.assertIn(f".{class_name}", bundle)
        # 列表项是脚本拼的，类名只出现在 JS 里，别漏
        for class_name in ("notif-item", "notif-item-icon", "notif-item-main", "notif-dot", "notif-empty"):
            self.assertIn(f".{class_name}", bundle)
        self.assertIn("bell-shake", bundle)

    def test_source_lives_in_the_shared_layer(self):
        """源头在 static/src/_shared.css：改产物会被下次构建冲掉。"""
        shared = _read(STATIC / "src" / "_shared.css")
        self.assertIn(".notif-panel {", shared)
        self.assertIn(".notif-item {", shared)

    def test_every_theme_overrides_the_panel(self):
        """四个主题都要有适配：毛玻璃与漫画各自有风格约束，不能只靠通用层。"""
        comic = _read(STATIC / "comic-style.css")
        vibrancy = _read(STATIC / "macos-vibrancy.css")
        for name, sheet in (("comic", comic), ("vibrancy", vibrancy)):
            self.assertIn(".notif-panel", sheet, f"{name} 主题没有通知面板适配")
            self.assertIn(".notif-badge", sheet, f"{name} 主题没有通知徽标适配")
        self.assertIn("data-theme=\"comic\"", comic)
        self.assertIn("data-theme=\"vibrancy\"", vibrancy)
