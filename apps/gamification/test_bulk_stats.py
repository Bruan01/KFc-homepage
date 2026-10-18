# pyright: reportMissingImports=false
"""批量用户统计：必须与逐人统计完全等价，且查询数与人数无关。

点赞/评论这类高频写路径会同时给「操作者 + 作者」两人做统计并判勋章。
改造前是每人各跑一遍 compute_user_stats（各 13 次查询），现在走
compute_users_stats / check_users_achievements 的批量版本。
"""
import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.forum.models import (
    ForumCategory, ForumLike, ForumReply, ForumReplyLike, ForumTopic, TopicBoost,
)
from apps.learn.models import LearnProgress
from apps.points.models import UserDailyActivity
from apps.rankings.models import ExternalProject, ExternalProjectVote
from apps.store.models import ListingRedemption, StoreListing

from .services import (
    check_user_achievements, check_users_achievements,
    compute_user_stats, compute_users_stats,
)


class BulkStatsTests(TestCase):
    def setUp(self):
        self.cat = ForumCategory.objects.create(
            slug="test", name="测试", icon="测", color="#d9232e", sort_order=1,
        )
        self.alice = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        self.bob = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")

    def _seed(self):
        t1 = ForumTopic.objects.create(category=self.cat, title="a1", content="c", author_username="alice")
        t2 = ForumTopic.objects.create(category=self.cat, title="a2", content="c", author_username="alice")
        t3 = ForumTopic.objects.create(category=self.cat, title="b1", content="c", author_username="bob")
        ForumTopic.objects.create(
            category=self.cat, title="closed", content="c",
            author_username="alice", status="closed",
        )
        r1 = ForumReply.objects.create(topic=t3, author_username="alice", content="hi")
        ForumReply.objects.create(topic=t1, author_username="bob", content="hi", is_deleted=True)
        ForumLike.objects.create(topic=t1, username="bob")
        ForumLike.objects.create(topic=t2, username="bob")
        ForumLike.objects.create(topic=t1, username="alice")
        ForumLike.objects.create(topic=t3, username="alice")
        ForumReplyLike.objects.create(reply=r1, username="bob")
        ForumReplyLike.objects.create(reply=r1, username="alice")
        UserDailyActivity.objects.create(user=self.alice, activity_date="2026-10-01")
        UserDailyActivity.objects.create(user=self.alice, activity_date="2026-10-02")
        UserDailyActivity.objects.create(user=self.bob, activity_date="2026-10-02")
        LearnProgress.objects.create(user=self.alice, kind="tutorial", slug="t1")
        LearnProgress.objects.create(user=self.alice, kind="term", slug="g1")
        LearnProgress.objects.create(user=self.bob, kind="term", slug="g2")
        project = ExternalProject.objects.create(
            source="kaiyuanbang", external_id="x1", title="p", url="http://x/1", author="a",
            description="d", heat_score=1.0, votes=0, tags=json.dumps(["AI"]),
            metrics=json.dumps({"stars": 1}),
            last_crawled_at=timezone.now(), pushed_at=timezone.now(),
        )
        ExternalProjectVote.objects.create(project=project, username="alice")
        TopicBoost.objects.create(
            topic=t1, username="alice", tier="small", points_cost=10, boost_score=1,
            starts_at=timezone.now(), ends_at=timezone.now(),
        )
        listing = StoreListing.objects.create(
            seller_username="bob", title="t", price_points=100, status="active",
        )
        ListingRedemption.objects.create(
            listing=listing, buyer=self.alice, buyer_username="alice", seller_username="bob",
            points_paid=100, seller_earning=100, delivered_payload="{}", idempotency_key="k1",
        )

    def test_bulk_matches_single(self):
        self._seed()
        # 故意重复传 alice，验证批量实现对重复用户去重后仍给出一致结果
        bulk = compute_users_stats([self.alice, self.bob, self.alice])
        for user in (self.alice, self.bob):
            self.assertEqual(bulk[user.pk], compute_user_stats(user), f"{user.username} 统计不一致")

    def test_bulk_query_count_is_flat(self):
        self._seed()
        with CaptureQueriesContext(connection) as one:
            compute_users_stats([self.alice])
        with CaptureQueriesContext(connection) as two:
            compute_users_stats([self.alice, self.bob])
        self.assertEqual(
            len(two.captured_queries), len(one.captured_queries),
            "批量统计的查询数不应随人数增长",
        )

    def test_bulk_beats_two_single_calls(self):
        """两人批量必须比两次单人统计更省查询，否则改造没有意义。"""
        self._seed()
        with CaptureQueriesContext(connection) as bulk:
            compute_users_stats([self.alice, self.bob])
        with CaptureQueriesContext(connection) as single:
            compute_user_stats(self.alice)
            compute_user_stats(self.bob)
        self.assertLess(len(bulk.captured_queries), len(single.captured_queries))

    def test_bulk_achievements_match_single(self):
        """两个处境完全相同的用户，一个走逐人版、一个走批量版，授予的勋章必须一致。"""
        self._seed()
        from .management.commands.seed_achievements import Command

        Command().handle()  # 建出 BADGE_RULES 引用的勋章定义

        single_user = User.objects.create_user(username="carol", password="pass1234", email="c@example.com")
        ForumTopic.objects.create(category=self.cat, title="c1", content="c", author_username="carol")
        ForumLike.objects.create(
            topic=ForumTopic.objects.create(category=self.cat, title="c2", content="c", author_username="carol"),
            username="bob",
        )
        bulk_user = User.objects.create_user(username="dave", password="pass1234", email="d@example.com")
        ForumTopic.objects.create(category=self.cat, title="d1", content="c", author_username="dave")
        ForumLike.objects.create(
            topic=ForumTopic.objects.create(category=self.cat, title="d2", content="c", author_username="dave"),
            username="bob",
        )

        single_codes = sorted(a.code for a in check_user_achievements(single_user))
        bulk_grants = check_users_achievements([bulk_user])
        bulk_codes = sorted(a.code for a in bulk_grants.get(bulk_user.username, []))
        self.assertTrue(single_codes, "测试前置条件不足：逐人版没授出任何勋章")
        self.assertEqual(bulk_codes, single_codes, "批量勋章判定与逐人判定结果不一致")

    def test_bulk_handles_empty_input(self):
        self.assertEqual(compute_users_stats([]), {})
        self.assertEqual(check_users_achievements([]), {})
