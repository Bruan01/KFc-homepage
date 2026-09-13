# pyright: reportMissingImports=false
"""Tests for showcase badge (佩戴展示)."""
import json

from django.test import TestCase

from apps.accounts.models import User
from apps.gamification.models import Achievement, UserAchievement, UserStats


def _make_user(username):
    user = User.objects.create_user(username=username, password="pass1234", email=f"{username}@example.com")
    return user


def _grant(user, code="liked_25", name="人气成员"):
    achievement, _ = Achievement.objects.get_or_create(
        code=code, defaults={"name": name, "icon": "heart", "tier": "silver", "category": "interaction"}
    )
    UserAchievement.objects.get_or_create(user=user, achievement=achievement)
    return achievement


class ShowcaseAPITests(TestCase):
    def setUp(self):
        self.user = _make_user("alice")
        self.achievement = _grant(self.user)
        self.client.login(username="alice", password="pass1234")

    def test_set_showcase_own_badge(self):
        resp = self.client.post(
            "/api/achievements/showcase",
            json.dumps({"code": "liked_25"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        stats = UserStats.objects.get(user=self.user)
        self.assertEqual(stats.showcase.code, "liked_25")

    def test_cannot_showcase_unowned_badge(self):
        Achievement.objects.get_or_create(code="pillar_500", defaults={"name": "中流砥柱", "icon": "trophy", "tier": "gold"})
        resp = self.client.post(
            "/api/achievements/showcase",
            json.dumps({"code": "pillar_500"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_clear_showcase(self):
        stats = UserStats.objects.create(user=self.user)
        stats.showcase = self.achievement
        stats.save()
        resp = self.client.post(
            "/api/achievements/showcase",
            json.dumps({"code": ""}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        stats.refresh_from_db()
        self.assertIsNone(stats.showcase)

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.post(
            "/api/achievements/showcase",
            json.dumps({"code": "liked_25"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_topic_payload_includes_showcase(self):
        from apps.forum.models import ForumCategory, ForumTopic

        cat = ForumCategory.objects.create(slug="t", name="T", icon="t", color="#000", sort_order=1)
        ForumTopic.objects.create(category=cat, title="帖子", content="c", author_username="alice")
        stats = UserStats.objects.create(user=self.user)
        stats.showcase = self.achievement
        stats.save(update_fields=["showcase"])
        resp = self.client.get("/api/forum/topics")
        items = resp.json()["items"]
        author = next(i["author_profile"] for i in items if i["title"] == "帖子")
        self.assertEqual(author["showcase"]["name"], "人气成员")

    def test_achievements_api_includes_showcase_code(self):
        stats = UserStats.objects.create(user=self.user)
        stats.showcase = self.achievement
        stats.save(update_fields=["showcase"])
        resp = self.client.get("/api/achievements")
        self.assertEqual(resp.json()["showcaseCode"], "liked_25")
