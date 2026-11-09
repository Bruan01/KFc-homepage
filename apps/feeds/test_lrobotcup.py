# pyright: reportMissingImports=false
"""LRobotcup 后端改造：具身智能信源种子 + 周报命令（临时测试库）。

只调用命令、断言 DB 结果，不触碰 data/homepage.db；信源种子读
output/lrc-news-seed.json 为只读。
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import OfficialCommunitySettings, User
from apps.forum.models import ForumCategory, ForumTopic

from .models import FeedItem, FeedSource


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
