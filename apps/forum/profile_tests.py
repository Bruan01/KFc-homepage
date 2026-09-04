# pyright: reportMissingImports=false
"""Tests for forum user profiles."""
import json

from django.test import TestCase

from apps.accounts.models import User
from apps.forum.models import ForumCategory, ForumReply, ForumTopic


class ForumProfileAPITests(TestCase):
    def setUp(self):
        self.category = ForumCategory.objects.create(slug="profile", name="资料测试")
        self.user = User.objects.create_user(username="alice", password="test-profile-password", email="alice@example.com")
        self.user.display_name = "Alice 昵称"
        self.user.avatar_url = "https://example.com/avatar.png"
        self.user.bio = "我是 Alice"
        self.user.save(update_fields=["display_name", "avatar_url", "bio"])
        self.topic = ForumTopic.objects.create(
            category=self.category,
            title="Alice 的话题",
            content="正文内容",
            author_username="alice",
        )
        self.reply = ForumReply.objects.create(topic=self.topic, author_username="alice", content="Alice 的回复")

    def test_public_profile_exposes_safe_profile_and_activity(self):
        response = self.client.get("/api/forum/users/alice")
        self.assertEqual(response.status_code, 200)
        profile = response.json()["profile"]
        self.assertEqual(profile["display_name"], "Alice 昵称")
        self.assertNotIn("email", profile)
        self.assertEqual(profile["topic_count"], 1)
        self.assertEqual(profile["reply_count"], 1)
        self.assertEqual(profile["topics"][0]["title"], "Alice 的话题")
        self.assertEqual(profile["replies"][0]["topic_title"], "Alice 的话题")

    def test_missing_profile_user_returns_404(self):
        self.assertEqual(self.client.get("/api/forum/users/missing").status_code, 404)

    def test_my_profile_requires_login(self):
        response = self.client.get("/api/forum/users/me/profile")
        self.assertEqual(response.status_code, 401)

    def test_update_profile_only_changes_profile_fields(self):
        self.client.login(username="alice", password="test-profile-password")
        original_email = self.user.email
        response = self.client.patch(
            "/api/forum/users/me/profile/update",
            data=json.dumps({
                "display_name": "新昵称",
                "avatar_url": "/uploads/avatar.png",
                "bio": "新的介绍",
                "email": "attacker@example.com",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "新昵称")
        self.assertEqual(self.user.avatar_url, "/uploads/avatar.png")
        self.assertEqual(self.user.bio, "新的介绍")
        self.assertEqual(self.user.email, original_email)

    def test_update_rejects_insecure_avatar_url(self):
        self.client.login(username="alice", password="test-profile-password")
        response = self.client.patch(
            "/api/forum/users/me/profile/update",
            data=json.dumps({"avatar_url": "http://evil.example/avatar.png"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_history_author_without_account_still_renders(self):
        topic = ForumTopic.objects.create(
            category=self.category,
            title="历史作者",
            content="旧数据",
            author_username="legacy-author",
        )
        response = self.client.get(f"/api/forum/topics/{topic.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["topic"]["author_profile"]["display_name"], "legacy-author")
