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
from apps.stats.models import VisitDaily


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
        yesterday = (today - timedelta(days=1)).isoformat()
        self.user = User.objects.create(username="visitor-1", password="x", created_at=now.isoformat())
        UserDailyActivity.objects.create(user=self.user, activity_date=yesterday, created_at=now.isoformat())
        UserDailyActivity.objects.create(user=self.user, activity_date=self.today, created_at=now.isoformat())
        VisitDaily.objects.create(date=self.today, pv=10, uv=4)
        category = ForumCategory.objects.create(slug="dashboard-test", name="综合")
        self.topics_before = ForumTopic.objects.exclude(status=ForumTopic.STATUS_DELETED).count()
        self.murmurs_before = Murmur.objects.filter(is_deleted=False).count()
        ForumTopic.objects.create(category=category, title="今天的帖子", content="正文", author_username="visitor-1")
        Murmur.objects.create(author_username="visitor-1", client_key="murmur-1", created_at=now.isoformat())
        base = {
            "user": self.user,
            "prompt": "一只猫",
            "size": "1024x1024",
            "quality": "high",
            "output_format": "png",
        }
        ImageGenerationJob.objects.create(**base, idempotency_key="done-1", status="completed")
        ImageGenerationJob.objects.create(**base, idempotency_key="fail-1", status="failed")

    def test_community_metrics_follow_local_day(self):
        response = self.client.get("/api/admin/dashboard")
        self.assertEqual(response.status_code, 200, response.content)
        community = response.json()["community"]
        self.assertEqual(community["date"], self.today)
        self.assertEqual(community["users_total"], 1)
        self.assertEqual(community["users_new_today"], 1)
        self.assertEqual(community["users_active_today"], 1)
        self.assertEqual(community["users_active_yesterday"], 1)
        self.assertEqual(community["users_retained_today"], 1)
        self.assertEqual(community["retention_next_day"], 100.0)
        self.assertEqual(community["topics_today"], self.topics_before + 1)
        self.assertEqual(community["murmurs_today"], self.murmurs_before + 1)
        self.assertEqual(community["imaging_completed_today"], 1)
        self.assertEqual(community["imaging_failed_today"], 1)
        self.assertEqual(community["uv_today"], 4)
        self.assertEqual(community["signup_conversion"], 25.0)

    def test_retention_is_null_without_yesterday_activity(self):
        UserDailyActivity.objects.filter(activity_date=(timezone.localdate() - timedelta(days=1)).isoformat()).delete()
        community = self.client.get("/api/admin/dashboard").json()["community"]
        self.assertEqual(community["users_active_yesterday"], 0)
        self.assertIsNone(community["retention_next_day"])
