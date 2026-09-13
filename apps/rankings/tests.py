# pyright: reportMissingImports=false
"""Tests for rankings APIs."""
from django.test import TestCase
from django.utils import timezone

from apps.forum.models import ForumCategory, ForumTopic
from apps.points.models import PointAccount, PointLedger

from .models import CrawlRun, ExternalProject, ExternalProjectVote


class SiteRankingsTests(TestCase):
    def setUp(self):
        self.cat = ForumCategory.objects.create(slug="test", name="测试", icon="测", color="#000", sort_order=1)
        self.hot = ForumTopic.objects.create(category=self.cat, title="热帖", content="c", author_username="a", hot_score=42.0)
        self.cold = ForumTopic.objects.create(category=self.cat, title="冷帖", content="c", author_username="b", hot_score=1.0)
        ForumTopic.objects.create(category=self.cat, title="已删", content="c", author_username="c", hot_score=99.0, status="deleted")

    def test_ordering_by_hot_score(self):
        resp = self.client.get("/api/rankings/site?period=all")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertEqual(items[0]["title"], "热帖")
        self.assertEqual(items[1]["title"], "冷帖")
        self.assertEqual(items[0]["rank"], 1)

    def test_creators_board(self):
        from apps.accounts.models import User

        u = User.objects.create_user(username="creator", password="pass1234", email="c@example.com")
        PointAccount.objects.create(user=u, balance=0, contribution_score=77, updated_at="2026-01-01T00:00:00+00:00")
        resp = self.client.get("/api/rankings/creators")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(any(row["username"] == "creator" for row in items))


class ExternalRankingsTests(TestCase):
    def setUp(self):
        self.project = ExternalProject.objects.create(
            source="github",
            external_id="123",
            title="vibe-snake",
            description="A vibe coded snake",
            url="https://github.com/x/vibe-snake",
            metrics='{"stars": 1200, "forks": 30}',
            heat_score=631.0,
            last_crawled_at=timezone.now(),
        )

    def test_external_board(self):
        resp = self.client.get("/api/rankings/external")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metrics"]["stars"], 1200)

    def test_source_filter(self):
        resp = self.client.get("/api/rankings/external?source=producthunt")
        self.assertEqual(resp.json()["items"], [])

    def test_vote_requires_login(self):
        resp = self.client.post(f"/api/rankings/external/{self.project.pk}/vote")
        self.assertEqual(resp.status_code, 401)

    def test_vote_counts_once_per_user(self):
        from apps.accounts.models import User

        User.objects.create_user(username="voter", password="pass1234", email="v@example.com")
        self.client.login(username="voter", password="pass1234")
        first = self.client.post(f"/api/rankings/external/{self.project.pk}/vote")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["votes"], 1)
        second = self.client.post(f"/api/rankings/external/{self.project.pk}/vote")
        self.assertEqual(second.json()["votes"], 1)  # idempotent
        self.assertEqual(ExternalProjectVote.objects.count(), 1)
