# pyright: reportMissingImports=false
"""LRobotcup 后端改造：论坛 tag 精确筛选 + 冷启动种子命令幂等。

这些测试用 Django 临时测试库（TestCase 事务回滚），不触碰 data/homepage.db。
"""
from io import StringIO

from django.core.management import call_command
from django.db.models import Max
from django.test import TestCase

from apps.accounts.models import OfficialCommunitySettings, User
from apps.forum.models import ForumCategory, ForumTopic


class ForumTagFilterTests(TestCase):
    """GET /api/forum/topics?tag= 精确匹配逗号分隔标签中的一项。"""

    def setUp(self):
        self.cat = ForumCategory.objects.create(
            slug="embodied-ai", name="具身智能", icon="🤖", sort_order=1,
        )
        # 精确命中
        ForumTopic.objects.create(
            category=self.cat, title="VLA 方向讨论", author_username="alice",
            tags="具身智能,行业动态", status=ForumTopic.STATUS_OPEN, content="正文",
        )
        # 相似但不应命中（tag=具身智能 不能误中「具身智能入门」）
        ForumTopic.objects.create(
            category=self.cat, title="新手入门指南", author_username="bob",
            tags="具身智能入门,VLA", status=ForumTopic.STATUS_OPEN, content="正文",
        )
        # 无关标签
        ForumTopic.objects.create(
            category=self.cat, title="运动控制部署", author_username="carol",
            tags="运动控制,部署", status=ForumTopic.STATUS_OPEN, content="正文",
        )

    def test_tag_exact_match_is_guest_accessible(self):
        resp = self.client.get("/api/forum/topics", {"tag": "具身智能"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["title"], "VLA 方向讨论")
        self.assertIn("具身智能", data["items"][0]["tags"])

    def test_tag_does_not_match_similar_tag(self):
        resp = self.client.get("/api/forum/topics", {"tag": "具身智能"})
        titles = [item["title"] for item in resp.json()["items"]]
        self.assertNotIn("新手入门指南", titles)
        self.assertNotIn("运动控制部署", titles)

    def test_tag_stacks_with_q(self):
        # q 与 tag 为 AND：都满足才命中
        self.assertEqual(
            self.client.get("/api/forum/topics", {"tag": "具身智能", "q": "讨论"}).json()["total"],
            1,
        )
        # q 指向相似标签帖，但精确 tag 不满足 -> 0
        self.assertEqual(
            self.client.get("/api/forum/topics", {"tag": "具身智能", "q": "指南"}).json()["total"],
            0,
        )

    def test_tag_pagination_total_is_correct(self):
        for i in range(3):
            ForumTopic.objects.create(
                category=self.cat, title=f"具身智能 {i}", author_username="u",
                tags="具身智能", status=ForumTopic.STATUS_OPEN, content="正文",
            )
        data = self.client.get(
            "/api/forum/topics", {"tag": "具身智能", "page": 1, "page_size": 2},
        ).json()
        self.assertEqual(data["total"], 4)  # 1 命中 + 3 新增
        self.assertEqual(len(data["items"]), 2)
        self.assertTrue(data["has_next"])


class SeedLRobotcupCommandTests(TestCase):
    """seed_lrobotcup（论坛冷启动）执行两次后分类数与帖子数不增长。"""

    def setUp(self):
        self.official = User.objects.create_user(
            username="xiaok", password="pass1234", email="x@example.com",
        )
        OfficialCommunitySettings.objects.create(account=self.official)

    def test_seed_creates_board_and_posts_then_is_idempotent(self):
        max_sort_before = ForumCategory.objects.aggregate(Max("sort_order"))["sort_order__max"] or 0
        call_command("seed_lrobotcup", stdout=StringIO())

        board = ForumCategory.objects.get(slug="embodied-ai")
        self.assertEqual(board.name, "具身智能")
        self.assertEqual(board.icon, "🤖")
        self.assertTrue(board.is_active)
        self.assertEqual(board.sort_order, max_sort_before + 1)

        posts = ForumTopic.objects.filter(category=board)
        self.assertEqual(posts.count(), 8)
        self.assertEqual(posts.filter(status=ForumTopic.STATUS_OPEN).count(), 8)
        self.assertTrue(posts.filter(is_pinned=True).exists())
        for post in posts:
            self.assertIn("具身智能", post.tag_list)
            self.assertIn("讨论引导", post.content)
            self.assertGreaterEqual(len(post.content), 150)

        cat_count = ForumCategory.objects.count()
        topic_count = ForumTopic.objects.count()

        # 重复执行：不新增、不覆盖
        call_command("seed_lrobotcup", stdout=StringIO())
        self.assertEqual(ForumCategory.objects.count(), cat_count)
        self.assertEqual(ForumTopic.objects.count(), topic_count)
        self.assertEqual(ForumTopic.objects.filter(category__slug="embodied-ai").count(), 8)
