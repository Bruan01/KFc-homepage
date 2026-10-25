import json
# pyright: reportMissingImports=false
"""Tests for in-site notifications."""
from django.test import TestCase

from apps.accounts.models import User
from apps.forum.models import ForumCategory, ForumReply, ForumTopic
from apps.gamification.models import Achievement
from apps.messaging.models import PrivateMessage
from apps.notifications.models import Notification
from apps.notifications.services import category_counts, notify, unread_count


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

    def test_imaging_completion_counts_as_a_system_notification(self):
        notify(recipient=self.alice, type_="imaging", title="显影已完成")
        self.assertEqual(unread_count(self.alice), 1)
        self.assertEqual(category_counts(self.alice)["system"], 1)
        self.assertEqual(Notification.objects.get(recipient=self.alice).type, "imaging")


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


class DirectMessageNotificationTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        self.bob = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")

    def _send(self, username, content, key):
        return self.client.post(
            f"/api/messages/{username}",
            json.dumps({"content": content, "client_key": key}),
            content_type="application/json",
        )

    def test_same_sender_keeps_one_notification_with_a_count(self):
        self.client.login(username="bob", password="pass1234")
        for index, key in enumerate(("dm-merge-0001", "dm-merge-0002")):
            self.assertEqual(self._send("alice", f"第{index + 1}条", key).status_code, 201)
        rows = Notification.objects.filter(recipient=self.alice, type="message")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().body, "你有 2 条新私信")
        self.assertEqual(unread_count(self.alice), 1)

    def test_list_merges_legacy_duplicates_and_reads_the_whole_group(self):
        for _ in range(3):
            Notification.objects.create(
                recipient=self.alice, type="message", title="bob 给你发来私信",
                body="你有一条新私信", link="/messages?user=bob", actor_username="bob",
            )
        PrivateMessage.objects.create(sender=self.bob, recipient=self.alice, content="a", client_key="merge-0001")
        PrivateMessage.objects.create(sender=self.bob, recipient=self.alice, content="b", client_key="merge-0002")
        self.client.login(username="alice", password="pass1234")
        data = self.client.get("/api/notifications").json()
        messages = [item for item in data["items"] if item["type"] == "message"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["body"], "你有 2 条新私信")
        self.assertEqual(len(messages[0]["ids"]), 3)
        self.assertEqual(data["unreadCount"], 1)
        resp = self.client.post(
            "/api/notifications/mark-read",
            json.dumps({"ids": [messages[0]["id"]]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Notification.objects.filter(recipient=self.alice, is_read=False).exists())
        self.assertEqual(unread_count(self.alice), 0)
