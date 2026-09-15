# pyright: reportMissingImports=false
"""Integration tests for vibecoding community features (images, links, boost, reply likes)."""
import json

from django.test import TestCase

from apps.accounts.models import User
from apps.forum.models import (
    ForumCategory,
    ForumLike,
    ForumReply,
    ForumReplyLike,
    ForumTopic,
    ForumTopicLink,
    TopicBoost,
    TopicViewLog,
)
from apps.points.models import PointAccount
from .services import compute_hot_score, refresh_hot_scores, refund_active_boosts


def _reset_forum_data():
    TopicBoost.objects.all().delete()
    TopicViewLog.objects.all().delete()
    ForumReplyLike.objects.all().delete()
    ForumLike.objects.all().delete()
    ForumReply.objects.all().delete()
    ForumTopic.objects.all().delete()
    ForumTopicLink.objects.all().delete()
    ForumCategory.objects.all().delete()


class TopicLinksAndPointsTests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = ForumCategory.objects.create(slug="showcase", name="晒作品", icon="晒", color="#d9232e", sort_order=1)
        self.user = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        PointAccount.objects.create(user=self.user, balance=0, updated_at="2026-01-01T00:00:00+00:00")

    def _login(self):
        self.client.login(username="alice", password="pass1234")

    def test_create_topic_with_links(self):
        self._login()
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({
                "title": "我的贪吃蛇",
                "content": "用一句话 vibe 出来的",
                "category": "showcase",
                "links": [
                    {"url": "https://github.com/alice/snake", "name": "源码"},
                    {"url": "https://gitee.com/alice/snake", "name": ""},
                    {"url": "https://snake.vercel.app", "name": ""},
                ],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        topic = ForumTopic.objects.get(title="我的贪吃蛇")
        links = {link.link_type for link in topic.links.all()}
        self.assertEqual(links, {"github", "gitee", "live"})
        payload = resp.json()["topic"]
        self.assertEqual(len(payload["links"]), 3)

    def test_create_topic_awards_points_once(self):
        self._login()
        first = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "第一帖", "content": "c", "category": "showcase"}),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 201)
        account = PointAccount.objects.get(user=self.user)
        self.assertEqual(account.balance, 10)
        # duplicate trigger for the same topic must not double-award
        topic = ForumTopic.objects.get(title="第一帖")
        from apps.points.services import award_topic_created

        award_topic_created(self.user, topic.pk)
        account.refresh_from_db()
        self.assertEqual(account.balance, 10)

    def test_like_topic_awards_author(self):
        self._login()
        topic = ForumTopic.objects.create(category=self.cat, title="被赞的帖", content="c", author_username="alice")
        author = User.objects.get(username="alice")
        liker = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")
        PointAccount.objects.create(user=liker, balance=0, updated_at="2026-01-01T00:00:00+00:00")
        self.client.logout()
        self.client.login(username="bob", password="pass1234")
        resp = self.client.post(f"/api/forum/topics/{topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        author_account = PointAccount.objects.get(user=author)
        self.assertEqual(author_account.balance, 1)  # like_received +1
        # self-like never awards
        from apps.points.services import award_like_received

        award_like_received(author, liker_username="alice", kind="topic", object_id=topic.pk)
        author_account.refresh_from_db()
        self.assertEqual(author_account.balance, 1)


class ReplyLikeTests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = ForumCategory.objects.create(slug="test", name="测试", icon="测", color="#000", sort_order=1)
        self.topic = ForumTopic.objects.create(category=self.cat, title="T", content="c", author_username="alice")
        self.reply = ForumReply.objects.create(topic=self.topic, author_username="alice", content="reply")
        self.liker = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")
        self.client.login(username="bob", password="pass1234")

    def test_like_and_unlike_reply(self):
        resp = self.client.post(f"/api/forum/replies/{self.reply.pk}/like")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["liked"])
        self.assertTrue(ForumReplyLike.objects.filter(reply=self.reply, username="bob").exists())
        resp = self.client.delete(f"/api/forum/replies/{self.reply.pk}/like")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["liked"])

    def test_topic_detail_includes_reply_like_state(self):
        ForumReplyLike.objects.create(reply=self.reply, username="bob")
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertEqual(resp.status_code, 200)
        reply = resp.json()["topic"]["replies_detail"][0]
        self.assertEqual(reply["likes"], 1)
        self.assertTrue(reply["liked"])


class DedupViewTests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = ForumCategory.objects.create(slug="test", name="测试", icon="测", color="#000", sort_order=1)
        self.topic = ForumTopic.objects.create(category=self.cat, title="T", content="c", author_username="alice")

    def test_dedup_counts_once_per_viewer_per_day(self):
        resp1 = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertEqual(resp1.status_code, 200)
        cookie = resp1.cookies.get("kflow_viewer")
        viewer = cookie.value if cookie else "fallback"
        self.client.cookies["kflow_viewer"] = viewer
        self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.dedup_views, 1)
        self.assertEqual(TopicViewLog.objects.count(), 1)

    def test_hot_score_uses_deduplicated_views(self):
        self.topic.views = 100
        self.topic.dedup_views = 2
        self.topic.save(update_fields=["views", "dedup_views"])
        refresh_hot_scores([self.topic.pk])
        self.topic.refresh_from_db()
        expected = compute_hot_score(self.topic, likes=0, replies=0, views=2)
        self.assertAlmostEqual(self.topic.hot_score, expected, places=4)


class BoostTests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = ForumCategory.objects.create(slug="test", name="测试", icon="测", color="#000", sort_order=1)
        self.author = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        PointAccount.objects.create(user=self.author, balance=1000, updated_at="2026-01-01T00:00:00+00:00")
        self.topic = ForumTopic.objects.create(category=self.cat, title="加热我", content="c", author_username="alice")
        self.client.login(username="alice", password="pass1234")

    def test_boost_tiers_visible(self):
        resp = self.client.get("/api/forum/boosts/tiers")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("small", resp.json()["tiers"])

    def test_boost_deducts_points_and_sets_active(self):
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/boost",
            json.dumps({"tier": "small"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        boost = TopicBoost.objects.get(topic=self.topic)
        self.assertEqual(boost.points_cost, 100)
        self.assertEqual(boost.boost_score, 300)
        account = PointAccount.objects.get(user=self.author)
        self.assertEqual(account.balance, 900)
        detail = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertTrue(detail.json()["topic"]["boosted"])

    def test_boost_idempotency_key_deducts_once(self):
        payload = json.dumps({"tier": "small", "idempotency_key": "boost-retry-1"})
        first = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/boost",
            payload,
            content_type="application/json",
        )
        second = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/boost",
            payload,
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(TopicBoost.objects.filter(topic=self.topic).count(), 1)
        self.assertEqual(PointAccount.objects.get(user=self.author).balance, 900)

    def test_refund_active_boosts_is_idempotent(self):
        self.client.post(
            f"/api/forum/topics/{self.topic.pk}/boost",
            json.dumps({"tier": "small", "idempotency_key": "refund-test"}),
            content_type="application/json",
        )
        self.topic.refresh_from_db()
        first = refund_active_boosts(self.topic, reason="测试下线")
        second = refund_active_boosts(self.topic, reason="重复下线")
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertGreater(PointAccount.objects.get(user=self.author).balance, 900)

    def test_cannot_boost_others_topic(self):
        other = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")
        PointAccount.objects.create(user=other, balance=1000, updated_at="2026-01-01T00:00:00+00:00")
        self.client.logout()
        self.client.login(username="bob", password="pass1234")
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/boost",
            json.dumps({"tier": "small"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_boost_returns_real_balance(self):
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/boost",
            json.dumps({"tier": "small"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["balance"], 900)  # 1000 - 100

    def test_boost_insufficient_points_message(self):
        account = PointAccount.objects.get(user=self.author)
        account.balance = 50
        account.save(update_fields=["balance"])
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/boost",
            json.dumps({"tier": "small"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 409)
        self.assertIn("积分不足", resp.json()["error"])

    def test_hot_view_orders_by_hot_score(self):
        resp = self.client.get("/api/forum/topics?view=hot")
        self.assertEqual(resp.status_code, 200)
