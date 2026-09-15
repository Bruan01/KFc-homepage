# pyright: reportMissingImports=false
"""Tests for the forum API endpoints."""
import json

from django.test import TestCase

from apps.accounts.models import User
from apps.forum.models import ForumCategory, ForumLike, ForumReply, ForumTopic


def _reset_forum_data():
    ForumLike.objects.all().delete()
    ForumReply.objects.all().delete()
    ForumTopic.objects.all().delete()
    ForumCategory.objects.all().delete()


def _make_category(**kwargs):
    defaults = {"slug": "test", "name": "测试分类", "icon": "测", "color": "#d9232e", "sort_order": 1}
    defaults.update(kwargs)
    return ForumCategory.objects.create(**defaults)


def _make_topic(category, **kwargs):
    defaults = {"title": "测试话题", "content": "话题内容", "author_username": "alice"}
    defaults.update(kwargs)
    return ForumTopic.objects.create(category=category, **defaults)


class ForumCategoryAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()

    def test_categories_returns_list(self):
        resp = self.client.get("/api/forum/categories")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("categories", data)
        self.assertEqual(len(data["categories"]), 1)
        self.assertEqual(data["categories"][0]["slug"], "test")

    def test_categories_include_topic_count(self):
        _make_topic(self.cat)
        resp = self.client.get("/api/forum/categories")
        self.assertEqual(resp.json()["categories"][0]["topic_count"], 1)


class ForumTopicListAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.t1 = _make_topic(self.cat, title="Alpha", author_username="alice")
        self.t2 = _make_topic(self.cat, title="Beta", author_username="bob")

    def test_topics_list_returns_all(self):
        resp = self.client.get("/api/forum/topics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 2)

    def test_topics_filter_by_category(self):
        cat2 = _make_category(slug="other", name="其他")
        _make_topic(cat2, title="Other topic")
        resp = self.client.get("/api/forum/topics?category=test")
        data = resp.json()
        self.assertEqual(data["total"], 2)

    def test_topics_search_by_title(self):
        resp = self.client.get("/api/forum/topics?q=Alpha")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["title"], "Alpha")

    def test_topics_search_by_author(self):
        resp = self.client.get("/api/forum/topics?q=bob")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["author"], "bob")

    def test_topics_view_featured(self):
        self.t1.is_featured = True
        self.t1.save()
        resp = self.client.get("/api/forum/topics?view=featured")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertTrue(data["items"][0]["featured"])

    def test_topics_pagination(self):
        # page_size is clamped to the API range 1..50.
        resp = self.client.get("/api/forum/topics?page=1&page_size=1")
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["total"], 2)
        self.assertTrue(data["has_next"])

    def test_topics_payload_fields(self):
        resp = self.client.get("/api/forum/topics")
        item = resp.json()["items"][0]
        for field in ("id", "title", "excerpt", "author", "category", "replies", "views", "likes", "liked", "active"):
            self.assertIn(field, item, f"missing field: {field}")

    def test_deleted_topic_excluded(self):
        self.t2.status = ForumTopic.STATUS_DELETED
        self.t2.save()
        resp = self.client.get("/api/forum/topics")
        self.assertEqual(resp.json()["total"], 1)


class ForumTopicDetailAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.topic = _make_topic(self.cat)

    def test_detail_returns_topic(self):
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("topic", data)
        self.assertEqual(data["topic"]["id"], self.topic.pk)

    def test_detail_increments_views(self):
        self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.client.get(f"/api/forum/topics/{self.topic.pk}")
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertEqual(resp.json()["topic"]["views"], 3)

    def test_detail_includes_replies(self):
        ForumReply.objects.create(topic=self.topic, author_username="bob", content="hi")
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        data = resp.json()
        self.assertEqual(len(data["topic"]["replies_detail"]), 1)
        self.assertEqual(data["topic"]["replies_detail"][0]["author"], "bob")

    def test_detail_paginates_replies_without_counting_extra_views(self):
        ForumReply.objects.bulk_create(
            [ForumReply(topic=self.topic, author_username="bob", content=f"reply {index}") for index in range(31)]
        )
        first = self.client.get(f"/api/forum/topics/{self.topic.pk}?reply_page_size=30")
        self.assertEqual(len(first.json()["topic"]["replies_detail"]), 30)
        self.assertTrue(first.json()["topic"]["reply_has_next"])
        second = self.client.get(f"/api/forum/topics/{self.topic.pk}?reply_page=2&reply_page_size=30")
        self.assertEqual(len(second.json()["topic"]["replies_detail"]), 1)
        self.assertFalse(second.json()["topic"]["reply_has_next"])
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.views, 1)

    def test_detail_404_for_missing(self):
        resp = self.client.get("/api/forum/topics/99999")
        self.assertEqual(resp.status_code, 404)

    def test_detail_404_for_deleted(self):
        self.topic.status = ForumTopic.STATUS_DELETED
        self.topic.save()
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertEqual(resp.status_code, 404)


class ForumCreateTopicAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.user = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")

    def _login(self):
        self.client.login(username="alice", password="pass1234")

    def test_create_requires_login(self):
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "t", "content": "c", "category": "test"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_topic_success(self):
        self._login()
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "新话题标题", "content": "详细内容描述", "category": "test", "tags": "Django, 测试"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["topic"]["title"], "新话题标题")
        self.assertEqual(data["topic"]["author"], "alice")
        self.assertIn("Django", data["topic"]["tags"])

    def test_create_validates_empty_title(self):
        self._login()
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "", "content": "c", "category": "test"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_validates_missing_category(self):
        self._login()
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "t", "content": "c", "category": "nonexistent"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_persists_in_db(self):
        self._login()
        self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "持久化测试", "content": "content", "category": "test"}),
            content_type="application/json",
        )
        self.assertTrue(ForumTopic.objects.filter(title="持久化测试").exists())


class ForumReplyAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.topic = _make_topic(self.cat)
        self.user = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")
        self.client.login(username="bob", password="pass1234")

    def test_reply_success(self):
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "这是一条回复"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["reply"]["author"], "bob")
        self.assertEqual(data["reply"]["content"], "这是一条回复")

    def test_reply_persists(self):
        self.client.post(
            f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "DB reply"}),
            content_type="application/json",
        )
        self.assertEqual(self.topic.replies.count(), 1)

    def test_reply_404_for_closed_topic(self):
        self.topic.status = ForumTopic.STATUS_CLOSED
        self.topic.save()
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "reply"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)


class ForumLikeAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.topic = _make_topic(self.cat)
        self.user = User.objects.create_user(username="carol", password="pass1234", email="c@example.com")
        self.client.login(username="carol", password="pass1234")

    def test_like_topic(self):
        resp = self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["likes"], 1)
        self.assertTrue(data["liked"])

    def test_unlike_topic(self):
        self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        resp = self.client.delete(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["likes"], 0)
        self.assertFalse(resp.json()["liked"])

    def test_like_idempotent(self):
        self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(ForumLike.objects.filter(topic=self.topic).count(), 1)

    def test_like_requires_login(self):
        self.client.logout()
        resp = self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 401)


class ForumStatsAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        _make_topic(self.cat)
        _make_topic(self.cat, title="Topic 2")
        User.objects.create_user(username="u1", password="p", email="u1@x.com")
        User.objects.create_user(username="u2", password="p", email="u2@x.com")

    def test_stats_returns_counts(self):
        resp = self.client.get("/api/forum/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["topics"], 2)
        self.assertGreaterEqual(data["members"], 2)
        self.assertIn("replies", data)
