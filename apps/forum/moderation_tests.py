# pyright: reportMissingImports=false
"""Tests for forum lifecycle, reports, and moderator actions."""
import json

from django.conf import settings
from django.test import TestCase

from apps.accounts.models import User

from .models import ForumCategory, ForumModerationAction, ForumReply, ForumReport, ForumTopic


class ForumModerationAPITests(TestCase):
    def setUp(self):
        self.category = ForumCategory.objects.create(slug="moderation", name="治理")
        self.author = User.objects.create_user(username="author", password="pass1234")
        self.reporter = User.objects.create_user(username="reporter", password="pass1234")
        self.topic = ForumTopic.objects.create(
            category=self.category,
            title="需要治理的话题",
            content="正文",
            author_username="author",
        )
        self.reply = ForumReply.objects.create(topic=self.topic, author_username="author", content="回复")

    def login(self, username):
        self.client.login(username=username, password="pass1234")

    def test_author_can_edit_and_delete_topic(self):
        self.login("author")
        edited = self.client.patch(
            f"/api/forum/topics/{self.topic.pk}/manage",
            data=json.dumps({"title": "新标题", "content": "新正文", "tags": "one,two"}),
            content_type="application/json",
        )
        self.assertEqual(edited.status_code, 200)
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.title, "新标题")
        deleted = self.client.delete(f"/api/forum/topics/{self.topic.pk}/manage")
        self.assertEqual(deleted.status_code, 200)
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.status, ForumTopic.STATUS_DELETED)

    def test_non_author_cannot_edit_or_delete_reply(self):
        self.login("reporter")
        response = self.client.patch(
            f"/api/forum/replies/{self.reply.pk}/manage",
            data=json.dumps({"content": "越权"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.delete(f"/api/forum/replies/{self.reply.pk}/manage").status_code, 403)

    def test_report_is_idempotent(self):
        self.login("reporter")
        path = f"/api/forum/topics/{self.topic.pk}/report"
        payload = json.dumps({"reason": "spam", "details": "重复广告"})
        first = self.client.post(path, data=payload, content_type="application/json")
        second = self.client.post(path, data=payload, content_type="application/json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(ForumReport.objects.count(), 1)

    def test_admin_can_resolve_report_and_remove_topic(self):
        self.login("reporter")
        report = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/report",
            data=json.dumps({"reason": "abuse"}),
            content_type="application/json",
        ).json()
        self.client.logout()
        admin_login = self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}),
            content_type="application/json",
        )
        self.assertEqual(admin_login.status_code, 200)
        listed = self.client.get("/api/admin/forum/reports")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["id"], report["report_id"])
        reviewed = self.client.post(
            f"/api/admin/forum/reports/{report['report_id']}/review",
            data=json.dumps({"decision": "resolved", "remove": True, "note": "确认违规"}),
            content_type="application/json",
        )
        self.assertEqual(reviewed.status_code, 200)
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.status, ForumTopic.STATUS_DELETED)
        self.assertEqual(ForumModerationAction.objects.filter(target_id=self.topic.pk).count(), 2)
