from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.forum.models import ForumCategory, ForumTopic
from apps.imaging.models import ImageGenerationJob
from apps.murmurs.models import Murmur
from apps.points.models import UserDailyActivity
from apps.stats.models import VisitVisitor


class DashboardTests(TestCase):
    def test_dashboard_requires_admin_and_returns_metrics(self):
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code,401)
        self.client.post("/api/admin/login",{"username":settings.ADMIN_USERNAME,"password":settings.ADMIN_PASSWORD},content_type="application/json")
        Product.objects.create(slug="dash",name="Dash",status="published",created_at="x",updated_at="x")
        response=self.client.get("/api/admin/dashboard")
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()["metrics"]["products_total"],1)
        self.assertTrue(response.json()["tables"])


class CommunityMetricsTests(TestCase):
    def setUp(self):
        # 直接写后台会话，避免 /api/admin/login 顺带创建 admin 的 User 行影响用户数
        session = self.client.session
        session["admin_username"] = "dash-admin"
        session["admin_level"] = 3
        session["admin_is_super"] = True
        session.save()

        now = timezone.now()
        today = timezone.localtime(now).date()
        self.today = today.isoformat()
        yesterday = today - timedelta(days=1)
        ten_days_ago = today - timedelta(days=10)

        self.topics_before = ForumTopic.objects.exclude(status=ForumTopic.STATUS_DELETED).count()
        self.murmurs_before = Murmur.objects.filter(is_deleted=False).count()

        self.user = User.objects.create(username="visitor-1", password="x", created_at=now.isoformat())
        old_user = User.objects.create(
            username="visitor-old",
            password="x",
            created_at=(now - timedelta(days=10)).isoformat(),
        )
        UserDailyActivity.objects.create(user=self.user, activity_date=yesterday.isoformat(), created_at=now.isoformat())
        UserDailyActivity.objects.create(user=self.user, activity_date=self.today, created_at=now.isoformat())
        UserDailyActivity.objects.create(user=old_user, activity_date=ten_days_ago.isoformat(), created_at=now.isoformat())

        VisitVisitor.objects.create(date=self.today, fingerprint="fp-today")
        VisitVisitor.objects.create(date=yesterday.isoformat(), fingerprint="fp-yesterday")
        VisitVisitor.objects.create(date=yesterday.isoformat(), fingerprint="fp-yesterday-2")
        VisitVisitor.objects.create(date=ten_days_ago.isoformat(), fingerprint="fp-old")

        category = ForumCategory.objects.create(slug="dashboard-test", name="综合")
        ForumTopic.objects.create(category=category, title="今天的帖子", content="正文", author_username="visitor-1")
        old_topic = ForumTopic.objects.create(category=category, title="旧帖子", content="正文", author_username="visitor-old")
        ForumTopic.objects.filter(pk=old_topic.pk).update(created_at=now - timedelta(days=10))
        Murmur.objects.create(author_username="visitor-1", client_key="murmur-1", created_at=now.isoformat())
        Murmur.objects.create(
            author_username="visitor-old",
            client_key="murmur-old",
            created_at=(now - timedelta(days=10)).isoformat(),
        )

        base = {
            "user": self.user,
            "prompt": "一只猫",
            "size": "1024x1024",
            "quality": "high",
            "output_format": "png",
        }
        ImageGenerationJob.objects.create(**base, idempotency_key="done-1", status="completed")
        ImageGenerationJob.objects.create(**base, idempotency_key="fail-1", status="failed")
        old_job = ImageGenerationJob.objects.create(**base, idempotency_key="fail-old", status="failed")
        ImageGenerationJob.objects.filter(pk=old_job.pk).update(created_at=now - timedelta(days=10))

    def community(self, range_key):
        response = self.client.get("/api/admin/dashboard/community", {"range": range_key})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["community"]

    def test_today_range_only_counts_today(self):
        data = self.community("today")
        self.assertEqual(data["range"], "today")
        self.assertEqual(data["range_label"], "今天")
        self.assertEqual(data["users_total"], 2)
        self.assertEqual(data["users_new"], 1)
        self.assertEqual(data["users_active"], 1)
        self.assertEqual(data["active_user_days"], 0)
        self.assertIsNone(data["retention_next_day"])
        self.assertEqual(data["topics"], self.topics_before + 1)
        self.assertEqual(data["murmurs"], self.murmurs_before + 1)
        self.assertEqual(data["imaging_completed"], 1)
        self.assertEqual(data["imaging_failed"], 1)
        self.assertEqual(data["uv"], 1)
        self.assertEqual(data["signup_conversion"], 100.0)

    def test_7d_range_includes_yesterday(self):
        data = self.community("7d")
        self.assertEqual(data["users_new"], 1)
        self.assertEqual(data["users_active"], 1)
        self.assertEqual(data["active_user_days"], 1)
        self.assertEqual(data["retained_user_days"], 1)
        self.assertEqual(data["retention_next_day"], 100.0)
        self.assertEqual(data["topics"], self.topics_before + 1)
        self.assertEqual(data["murmurs"], self.murmurs_before + 1)
        self.assertEqual(data["imaging_failed"], 1)
        self.assertEqual(data["uv"], 3)
        self.assertEqual(data["signup_conversion"], 33.3)

    def test_30d_range_adds_ten_day_old_activity(self):
        data = self.community("30d")
        self.assertEqual(data["users_new"], 2)
        self.assertEqual(data["users_active"], 2)
        self.assertEqual(data["active_user_days"], 2)
        self.assertEqual(data["retained_user_days"], 1)
        self.assertEqual(data["retention_next_day"], 50.0)
        self.assertEqual(data["topics"], self.topics_before + 2)
        self.assertEqual(data["murmurs"], self.murmurs_before + 2)
        self.assertEqual(data["imaging_failed"], 2)
        self.assertEqual(data["uv"], 4)
        self.assertEqual(data["signup_conversion"], 50.0)

    def test_dashboard_embeds_same_range_metrics(self):
        response = self.client.get("/api/admin/dashboard", {"range": "today"})
        self.assertEqual(response.status_code, 200, response.content)
        community = response.json()["community"]
        self.assertEqual(community["range"], "today")
        self.assertEqual(community["users_new"], 1)
        self.assertEqual(community["imaging_failed"], 1)
