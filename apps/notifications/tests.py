import json
# pyright: reportMissingImports=false
"""Tests for in-site notifications."""
from django.test import TestCase

from apps.accounts.models import User
from apps.forum.models import ForumCategory, ForumReply, ForumTopic
from apps.gamification.models import Achievement
from apps.notifications.models import Notification
from apps.notifications.services import notify, unread_count


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        self.bob = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")

    def test_notify_creates_row(self):
        notify(recipient=self.alice, type_="like", title="有人赞了你", actor_username="bob")
        self.assertEqual(unread_count(self.alice), 1)

    def test_self_notify_skipped(self):
        notify(recipient=self.alice, type_="like", title="自赞", actor_username="alice")
        self.assertEqual(unread_count(self.alice), 0)

    def test_notify_never_raises(self):
        notify(recipient=None, type_="like", title="x")
        self.assertEqual(unread_count(self.alice), 0)


class NotificationFlowTests(TestCase):
    def setUp(self):
        self.cat = ForumCategory.objects.create(slug="test", name="测试", icon="测", color="#000", sort_order=1)
        self.alice = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        self.bob = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")
        Achievement.objects.create(code="first_reply", name="初次开口", icon="bubble", tier="bronze", sort_order=2)
        self.topic = ForumTopic.objects.create(category=self.cat, title="被评论的帖", content="c", author_username="alice")

    def _login_bob(self):
        self.client.login(username="bob", password="pass1234")

    def test_reply_notifies_topic_author(self):
        self._login_bob()
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "好帖"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(unread_count(self.alice), 1)
        row = Notification.objects.get(recipient=self.alice)
        self.assertEqual(row.type, "reply")
        self.assertEqual(row.actor_username, "bob")

    def test_like_notifies_author(self):
        self._login_bob()
        resp = self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(unread_count(self.alice), 1)
        row = Notification.objects.get(recipient=self.alice)
        self.assertEqual(row.type, "like")

    def test_self_like_no_notification(self):
        self.client.login(username="alice", password="pass1234")
        self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(unread_count(self.alice), 0)

    def test_badge_creates_notification(self):
        reply = ForumReply.objects.create(topic=self.topic, author_username="bob", content="c")
        # bob 首次评论 → 初次开口勋章 → 同时产生一条 badge 通知
        self._login_bob()
        self.client.post(
            f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "再来一条"}),
            content_type="application/json",
        )
        bob_badge_note = Notification.objects.filter(recipient=self.bob, type="badge")
        self.assertTrue(bob_badge_note.exists())

    def test_mark_read_api(self):
        notify(recipient=self.alice, type_="system", title="公告", actor_username="system")
        self.client.login(username="alice", password="pass1234")
        row = Notification.objects.get(recipient=self.alice)
        resp = self.client.post(
            "/api/notifications/mark-read",
            json.dumps({"ids": [row.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(unread_count(self.alice), 0)

    def test_unread_count_api_requires_login(self):
        resp = self.client.get("/api/notifications/unread-count")
        self.assertEqual(resp.status_code, 401)
