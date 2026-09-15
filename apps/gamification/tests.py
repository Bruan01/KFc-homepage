# pyright: reportMissingImports=false
"""Tests for gamification: achievements, levels, stats APIs."""
import json

from django.test import TestCase

from apps.accounts.models import User
from apps.forum.models import ForumCategory, ForumLike, ForumTopic
from apps.points.models import PointAccount, UserDailyActivity

from .models import Achievement, UserAchievement, UserStats
from .management.commands.seed_achievements import BADGES
from .services import check_user_achievements, compute_level, compute_user_stats, promote_user_level


def _make_user(username, contribution=0, level=0):
    user = User.objects.create_user(username=username, password="pass1234", email=f"{username}@example.com")
    PointAccount.objects.get_or_create(
        user=user,
        defaults={"balance": 0, "contribution_score": contribution, "reputation_level": level,
                  "updated_at": "2026-01-01T00:00:00+00:00"},
    )
    return user


def _seed_badges():
    Achievement.objects.create(code="first_post", name="初来乍到", icon="pencil", tier="bronze", category="creation", sort_order=1)
    Achievement.objects.create(code="author_10", name="勤劳作者", icon="book", tier="silver", category="creation", sort_order=2)
    Achievement.objects.create(code="pillar_500", name="中流砥柱", icon="trophy", tier="gold", category="activity", sort_order=3)


class AchievementAwardTests(TestCase):
    def setUp(self):
        _seed_badges()
        self.cat = ForumCategory.objects.create(slug="test", name="测试", icon="测", color="#000", sort_order=1)

    def _post(self, username, title):
        return ForumTopic.objects.create(category=self.cat, title=title, content="c", author_username=username)

    def test_first_post_badge_awarded(self):
        user = _make_user("alice")
        self._post("alice", "第一帖")
        awarded = check_user_achievements(user)
        self.assertIn("first_post", [a.code for a in awarded])
        self.assertTrue(UserAchievement.objects.filter(user=user, achievement__code="first_post").exists())

    def test_award_is_idempotent(self):
        user = _make_user("bob")
        self._post("bob", "第一帖")
        check_user_achievements(user)
        second = check_user_achievements(user)
        self.assertEqual([a.code for a in second], [])
        self.assertEqual(UserAchievement.objects.filter(user=user).count(), 1)

    def test_silver_badge_requires_threshold(self):
        user = _make_user("carol")
        for i in range(3):
            self._post("carol", f"第 {i} 帖")
        check_user_achievements(user)
        self.assertFalse(UserAchievement.objects.filter(achievement__code="author_10", user=user).exists())

    def test_gold_pillar_from_contribution(self):
        user = _make_user("dave", contribution=500)
        awarded = check_user_achievements(user)
        self.assertIn("pillar_500", [a.code for a in awarded])

    def test_expanded_activity_badges_are_awarded(self):
        Achievement.objects.create(code="author_3", name="三作成行", icon="pencil", tier="bronze", category="creation", sort_order=21)
        Achievement.objects.create(code="contributor_1000", name="贡献灯塔", icon="trophy", tier="gold", category="activity", sort_order=32)
        user = _make_user("frank", contribution=1000)
        for index in range(3):
            self._post("frank", f"作品 {index + 1}")
        awarded = check_user_achievements(user)
        awarded_codes = {badge.code for badge in awarded}
        self.assertTrue({"author_3", "contributor_1000"}.issubset(awarded_codes))

    def test_max_topic_likes_is_highest_single_topic(self):
        user = _make_user("single-work")
        first = self._post("single-work", "第一篇")
        second = self._post("single-work", "第二篇")
        for index in range(3):
            ForumLike.objects.create(topic=first, username=f"reader-{index}")
        ForumLike.objects.create(topic=second, username="reader-extra")
        stats = compute_user_stats(user)
        self.assertEqual(stats["max_topic_likes"], 3)


class LevelTests(TestCase):
    def test_compute_level_ordering(self):
        base = {"active_days": 0, "topics": 0, "replies": 0, "likes_received": 0}
        self.assertEqual(compute_level(base, 0, 0), 0)
        lv1 = {**base, "active_days": 3, "topics": 1}
        self.assertEqual(compute_level(lv1, 0, 0), 1)
        lv2 = {**base, "active_days": 7, "topics": 3, "likes_received": 10}
        self.assertEqual(compute_level(lv2, 0, 0), 2)
        lv3 = {**base, "active_days": 30, "topics": 10, "likes_received": 50}
        self.assertEqual(compute_level(lv3, 200, 0), 3)

    def test_never_demotes(self):
        user = _make_user("eve", level=3)
        self.assertEqual(promote_user_level(user, stats={}), 3)

    def test_lv1_reply_alternative(self):
        stats = {"active_days": 3, "topics": 0, "replies": 3, "likes_received": 0}
        self.assertEqual(compute_level(stats, 0, 0), 1)


class GamificationAPITests(TestCase):
    def setUp(self):
        _seed_badges()
        self.user = _make_user("alice")

    def test_achievements_list_public(self):
        resp = self.client.get("/api/achievements")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["earned"], 0)
        codes = {item["code"] for item in data["items"]}
        self.assertIn("first_post", codes)
        holder_counts = {item["code"]: item["holderCount"] for item in data["items"]}
        self.assertEqual(holder_counts["first_post"], 0)

    def test_seed_catalog_includes_expanded_badges(self):
        codes = {row[0] for row in BADGES}
        self.assertGreaterEqual(len(BADGES), 32)
        self.assertTrue({"active_7", "study_6", "seller_5", "contributor_1000"}.issubset(codes))

    def test_levels_api_anonymous(self):
        resp = self.client.get("/api/levels")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["my"])
        self.assertEqual(len(resp.json()["levels"]), 5)

    def test_levels_api_with_progress(self):
        self.client.login(username="alice", password="pass1234")
        UserDailyActivity.objects.get_or_create(
            user=self.user, activity_date="2026-09-11", defaults={"created_at": "2026-09-11T00:00:00+00:00"}
        )
        resp = self.client.get("/api/levels")
        my = resp.json()["my"]
        self.assertEqual(my["level"], 0)
        self.assertIsNotNone(my["progress"])

    def test_profile_includes_badges_and_level(self):
        ForumTopic.objects.create(
            category=ForumCategory.objects.create(slug="t2", name="T2", icon="t", color="#000", sort_order=9),
            title="A", content="c", author_username="alice",
        )
        check_user_achievements(self.user)
        resp = self.client.get("/api/forum/users/alice")
        self.assertEqual(resp.status_code, 200)
        profile = resp.json()["profile"]
        self.assertEqual(profile["level"], 0)  # stats don't meet LV1 yet
        badge_names = [b["name"] for b in profile["badges"]]
        self.assertIn("初来乍到", badge_names)

    def test_admin_grant_core_member_sets_lv4(self):
        Achievement.objects.create(code="core_member", name="核心成员", icon="trophy", tier="gold", sort_order=19)
        User.objects.create_user(username="admin", password="pass1234", email="ad@example.com")
        self.client.login(username="admin", password="pass1234")
        resp = self.client.post(
            "/api/admin/gamification/grant",
            json.dumps({"username": "alice", "code": "core_member"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        account = PointAccount.objects.get(user=self.user)
        self.assertEqual(account.reputation_level, 4)
        self.assertTrue(UserAchievement.objects.filter(user=self.user, achievement__code="core_member").exists())

    def test_admin_revoke(self):
        _make_user("admin")  # ensure admin user row exists with account
        admin = User.objects.get(username="admin")
        PointAccount.objects.get_or_create(user=admin, defaults={"updated_at": "2026-01-01T00:00:00+00:00"})
        achievement = Achievement.objects.get(code="first_post")
        UserAchievement.objects.create(user=self.user, achievement=achievement)
        self.client.login(username="admin", password="pass1234")
        resp = self.client.post(
            "/api/admin/gamification/revoke",
            json.dumps({"username": "alice", "code": "first_post"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(UserAchievement.objects.filter(user=self.user).exists())


class StatsAPITests(TestCase):
    def setUp(self):
        self.cat = ForumCategory.objects.create(slug="test", name="测试", icon="测", color="#000", sort_order=1)
        self.user = _make_user("poster", contribution=100)
        ForumTopic.objects.create(category=self.cat, title="A", content="c", author_username="poster")

    def test_overview(self):
        resp = self.client.get("/api/stats/overview")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["topics"], 1)
        self.assertGreaterEqual(data["members"], 1)

    def test_contributors_ranked(self):
        resp = self.client.get("/api/stats/contributors?period=all")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(any(row["username"] == "poster" for row in items))
        poster = next(row for row in items if row["username"] == "poster")
        self.assertEqual(poster["topics"], 1)
        self.assertEqual(poster["contribution"], 100)
        self.assertGreater(poster["score"], 0)

    def test_contributors_period_filter(self):
        resp = self.client.get("/api/stats/contributors?period=weekly")
        self.assertEqual(resp.status_code, 200)
        # 帖子创建于测试时刻（now），周榜应包含
        self.assertTrue(any(row["username"] == "poster" for row in resp.json()["items"]))
