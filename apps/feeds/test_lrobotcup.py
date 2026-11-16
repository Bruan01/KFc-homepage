# pyright: reportMissingImports=false
"""LRobotcup 后端改造：具身智能信源种子 + 周报命令（临时测试库）。

只调用命令、断言 DB 结果，不触碰 data/homepage.db；信源种子读
output/lrc-news-seed.json 为只读。
"""
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import OfficialCommunitySettings, User
from apps.forum.models import ForumCategory, ForumTopic

from .models import FeedFetchRun, FeedItem, FeedSource


class SeedSourcesCommandTests(TestCase):
    def test_seed_is_idempotent_and_skips_unsupported_kind(self):
        call_command("seed_lrobotcup_sources", stdout=StringIO())
        sources = FeedSource.objects.filter(slug__startswith="lrc-")
        # 10 条里 1 条 feedKind=api（GitHub REST JSON）不受支持被跳过。
        self.assertEqual(sources.count(), 9)
        self.assertFalse(sources.filter(slug="lrc-github-lerobot-api").exists())
        for source in sources:
            self.assertEqual(source.category, "embodied-ai")
            self.assertEqual(source.fetch_kind, "rss")
            self.assertTrue(source.is_active)
            self.assertTrue(source.feed_url)

        # 重复执行不新增、不覆盖
        call_command("seed_lrobotcup_sources", stdout=StringIO())
        self.assertEqual(FeedSource.objects.filter(slug__startswith="lrc-").count(), 9)


class WeeklyCommandTests(TestCase):
    def setUp(self):
        self.official = User.objects.create_user(
            username="xiaok", password="pass1234", email="x@example.com",
        )
        OfficialCommunitySettings.objects.create(account=self.official)
        ForumCategory.objects.create(slug="embodied-ai", name="具身智能", icon="🤖", sort_order=1)
        self.source = FeedSource.objects.create(
            name="LeRobot Releases", slug="lrc-lerobot-releases",
            category="embodied-ai", site_url="https://github.com/huggingface/lerobot",
            feed_url="https://github.com/huggingface/lerobot/releases.atom",
            fetch_kind="rss", is_active=True,
        )

    def _add_item(self):
        return FeedItem.objects.create(
            source=self.source, title="LeRobot v0.6.1 发布",
            url="https://github.com/huggingface/lerobot/releases/tag/v0.6.1",
            guid="lrc-w1", summary="统一数据集格式", language="en",
            published_at=timezone.now() - timedelta(days=2),
        )

    def test_no_items_skips_empty_post_then_publishes_once(self):
        # 无条目：不发空帖
        call_command("publish_lrobotcup_weekly", stdout=StringIO())
        self.assertEqual(ForumTopic.objects.filter(author_username="xiaok").count(), 0)

        self._add_item()
        call_command("publish_lrobotcup_weekly", stdout=StringIO())
        topic = ForumTopic.objects.filter(author_username="xiaok").first()
        self.assertIsNotNone(topic)
        self.assertTrue(topic.title.startswith("具身智能行业周报"))
        self.assertRegex(topic.title, r"\d{4} 年第 \d{2} 周")  # 标题带年份周数
        self.assertEqual(topic.tags, "具身智能,行业动态,周报")
        self.assertEqual(topic.category.slug, "embodied-ai")
        # 每条含标题、来源、原文链接、发布时间
        self.assertIn("LeRobot v0.6.1 发布", topic.content)
        self.assertIn("来源：", topic.content)
        self.assertIn("https://github.com/huggingface/lerobot/releases/tag/v0.6.1", topic.content)
        self.assertIn("发布时间：", topic.content)
        # 帖子必须完整收尾，不能被 20000 字上限截断在半个链接里。
        self.assertTrue(topic.content.rstrip().endswith("实时动态见 /forum/lrobotcup 与 /feeds"))

        # 同一周重复执行不重复发帖
        call_command("publish_lrobotcup_weekly", stdout=StringIO())
        self.assertEqual(ForumTopic.objects.filter(author_username="xiaok").count(), 1)


class VerifyFeedsCommandTests(TestCase):
    """抓取链路自检：逐项断言信源/抓取/入库/新鲜度，--strict 控制退出码。"""

    def _seed_sources(self):
        call_command("seed_lrobotcup_sources", stdout=StringIO())

    def test_unhealthy_when_nothing_seeded(self):
        from apps.feeds.management.commands.verify_lrobotcup_feeds import collect_report
        report, checks = collect_report()
        self.assertFalse(report["healthy"])
        self.assertFalse(checks["sources_seeded"])
        self.assertFalse(checks["has_success_fetch"])
        self.assertFalse(checks["items_ingested"])

    def test_becomes_healthy_after_seed_fetch_and_runs(self):
        from apps.feeds.management.commands.verify_lrobotcup_feeds import collect_report
        self._seed_sources()
        source = FeedSource.objects.filter(slug__startswith="lrc-").first()
        FeedItem.objects.create(
            source=source, title="t", url="https://example.com/a", guid="g1",
            published_at=timezone.now(),
        )
        FeedFetchRun.objects.create(
            source_slug=source.slug, status=FeedFetchRun.STATUS_SUCCESS,
            item_count=1, finished_at=timezone.now(),
        )
        report, checks = collect_report()
        self.assertTrue(report["healthy"], report)
        self.assertTrue(all(checks.values()), checks)
        self.assertGreaterEqual(report["sources"]["total"], 9)
        self.assertEqual(report["items"]["total"], 1)

    def test_strict_exits_nonzero_when_unhealthy(self):
        # 测试库此刻还没 seed，健康判据应为否 → --strict 抛 SystemExit(1)。
        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("verify_lrobotcup_feeds", "--strict", "--json", stdout=out)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn('"healthy": false', out.getvalue())


class DeployScriptWiringTests(TestCase):
    """部署脚本必须真的配置具身智能链路，避免「部署了却永远抓不到」回归。"""

    def _src(self, rel):
        return (Path(settings.BASE_DIR) / rel).read_text(encoding="utf-8")

    def test_deploy_scripts_seed_lrobotcup_sources(self):
        # redeploy.sh 直接 seed；start.sh 通过专用脚本间接 seed，二者都覆盖到。
        self.assertIn("seed_lrobotcup_sources", self._src("redeploy.sh"))
        start = self._src("start.sh")
        self.assertIn("setup_lrobotcup_feeds.sh", start)
        self.assertIn("具身智能实时抓取链路", start)

    def test_dedicated_setup_script_is_complete_and_idempotent(self):
        script = self._src("scripts/setup_lrobotcup_feeds.sh")
        for command in ("seed_lrobotcup_sources", "seed_lrobotcup", "fetch_feeds",
                        "verify_lrobotcup_feeds", "setup_cron.sh"):
            with self.subTest(command=command):
                self.assertIn(command, script)
        self.assertIn("--strict", script)
        self.assertIn("--prune-days 0", script)
        self.assertIn("--verify-only", script)

    def test_redeploy_self_checks_after_fetch(self):
        self.assertIn("verify_lrobotcup_feeds", self._src("redeploy.sh"))
