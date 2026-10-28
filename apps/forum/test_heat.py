"""展示热度（论坛）接口测试：展示值只读计算，真实值保持不变。"""
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.heat import save_config
from .models import ForumCategory, ForumDisplayOverride, ForumLike, ForumTopic


class ForumHeatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="forum_heat_alice", password="test-password", created_at="2026-01-01T00:00:00+00:00")
        cls.bob = User.objects.create_user(username="forum_heat_bob", password="test-password", created_at="2026-01-01T00:00:00+00:00")
        cls.category = ForumCategory.objects.create(slug="heat-test", name="热度测试", icon="🔥", color="#ef4444")

    def setUp(self):
        self.client.force_login(self.alice)

    def topic(self, hours=48):
        row = ForumTopic.objects.create(
            category=self.category, title="热度曲线", content="正文内容", author_username=self.alice.username,
        )
        if hours:
            created = timezone.now() - timedelta(hours=hours)
            ForumTopic.objects.filter(pk=row.pk).update(created_at=created, updated_at=created)
            row.refresh_from_db()
        return row

    def enable_global(self, **overrides):
        values = {
            "enabled": True,
            "default_views": 300,
            "default_grow_days": 7,
            "default_like_ratio": 0.04,
            "quiet_minutes": 0,
            "max_views": 5000,
        }
        values.update(overrides)
        save_config("forum", values, "test-admin")

    def become_admin(self, level, superuser=False):
        session = self.client.session
        session["admin_username"] = "heat_reviewer"
        session["admin_level"] = level
        session["admin_is_super"] = superuser
        session.save()

    def list_item(self, topic_id):
        items = self.client.get("/api/forum/topics").json()["items"]
        return next(item for item in items if item["id"] == topic_id)

    def test_display_fields_default_to_real(self):
        topic = self.topic()
        item = self.list_item(topic.pk)
        self.assertEqual(item["display_views"], item["views"])
        self.assertEqual(item["display_likes"], item["likes"])

    def test_global_curve_boosts_forum_topics(self):
        self.enable_global()
        topic = self.topic()
        ForumLike.objects.create(topic=topic, username=self.bob.username)
        item = self.list_item(topic.pk)
        self.assertGreater(item["display_views"], 0)
        self.assertLessEqual(item["display_views"], 300)
        self.assertGreaterEqual(item["display_likes"], 1)

    def test_old_topics_keep_curve_values_instead_of_dropping(self):
        self.enable_global()
        topic = self.topic(hours=45 * 24)
        item = self.list_item(topic.pk)
        self.assertGreater(item["display_views"], 0)
        self.assertGreaterEqual(item["display_views"], 250)
        self.assertLessEqual(item["display_views"], 340)

    def test_disable_keeps_display_values_frozen(self):
        topic = self.topic()
        self.become_admin(3)
        url = f"/api/admin/forum/topics/{topic.pk}/heat"
        self.client.post(url, json.dumps({
            "target_views": 600, "grow_days": 1, "enabled": True,
        }), content_type="application/json")
        before = self.list_item(topic.pk)["display_views"]
        self.assertGreater(before, 0)
        self.client.post(url, json.dumps({"enabled": False}), content_type="application/json")
        after = self.list_item(topic.pk)["display_views"]
        self.assertEqual(after, before)
        # 恢复真实数字（显式删除）才会回落
        self.client.delete(url)
        real = self.list_item(topic.pk)
        self.assertEqual(real["display_views"], real["views"])

    def test_restore_forces_real_values_even_with_global_on(self):
        self.enable_global()
        topic = self.topic()
        self.become_admin(3)
        url = f"/api/admin/forum/topics/{topic.pk}/heat"
        self.client.post(url, json.dumps({
            "target_views": 600, "grow_days": 1, "enabled": True,
        }), content_type="application/json")
        self.assertGreater(self.list_item(topic.pk)["display_views"], 0)
        self.client.post(url, json.dumps({"enabled": False, "freeze": False}),
                         content_type="application/json")
        item = self.list_item(topic.pk)
        self.assertEqual(item["display_views"], item["views"])
        self.assertEqual(item["display_likes"], item["likes"])
        self.assertTrue(ForumDisplayOverride.objects.filter(topic=topic).exists())

    def test_global_restore_forces_real_values(self):
        self.enable_global()
        topic = self.topic()
        self.assertGreater(self.list_item(topic.pk)["display_views"], 0)
        self.become_admin(3)
        self.assertEqual(self.client.post("/api/admin/forum/heat/settings",
                                          json.dumps({"enabled": False, "restore": True}),
                                          content_type="application/json").status_code, 200)
        item = self.list_item(topic.pk)
        self.assertEqual(item["display_views"], item["views"])
        settings = self.client.get("/api/admin/forum/heat/settings").json()["settings"]
        self.assertFalse(settings["enabled"])
        self.assertEqual(settings["frozen_at"], "")

    def test_override_endpoints_are_level_3_only(self):
        topic = self.topic()
        url = f"/api/admin/forum/topics/{topic.pk}/heat"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.become_admin(2)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.become_admin(3)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/forum/heat/settings").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/forum/heat/posts?q=热度").status_code, 200)

    def test_override_save_and_reset(self):
        topic = self.topic()
        self.become_admin(3)
        url = f"/api/admin/forum/topics/{topic.pk}/heat"
        saved = self.client.post(url, json.dumps({
            "target_views": 600, "grow_days": 3, "target_likes": 0, "note": "推广", "enabled": True,
        }), content_type="application/json")
        self.assertEqual(saved.status_code, 200)
        override = ForumDisplayOverride.objects.get(topic=topic)
        self.assertEqual(override.note, "推广")
        item = self.list_item(topic.pk)
        self.assertGreaterEqual(item["display_views"], item["views"])
        self.assertLessEqual(item["display_views"], 660)
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertFalse(ForumDisplayOverride.objects.filter(topic=topic).exists())
        self.assertEqual(self.list_item(topic.pk)["display_views"], topic.views)

    def test_overrides_list_and_filter(self):
        first = self.topic()
        second = self.topic()
        self.become_admin(3)
        for topic, note in ((first, "推广一"), (second, "推广二")):
            self.client.post(f"/api/admin/forum/topics/{topic.pk}/heat", json.dumps({
                "target_views": 300, "grow_days": 7, "enabled": True, "note": note,
            }), content_type="application/json")
        data = self.client.get("/api/admin/forum/heat/overrides").json()
        self.assertEqual(data["total"], 2)
        self.assertEqual({item["id"] for item in data["items"]}, {first.pk, second.pk})
        filtered = self.client.get(f"/api/admin/forum/heat/overrides?q={first.pk}").json()
        self.assertEqual([item["id"] for item in filtered["items"]], [first.pk])
        self.assertEqual(filtered["items"][0]["override"]["note"], "推广一")
