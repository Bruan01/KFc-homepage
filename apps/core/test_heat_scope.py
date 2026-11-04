from datetime import timedelta

from django.conf import settings
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import AdminAccount, User
from apps.core.heat import admin_authors, author_config, display_counts, get_config, save_config
from apps.forum.models import ForumCategory, ForumDisplayOverride, ForumTopic
from apps.murmurs.models import Murmur, MurmurDisplayOverride


class HeatAuthorScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.names = ["scope_member", "scope_lv1", "scope_lv2", "scope_lv3", "scope_super", settings.ADMIN_USERNAME]
        for name in cls.names:
            User.objects.create(username=name, created_at="2026-01-01")
        for index, name in enumerate(cls.names[1:5]):
            AdminAccount.objects.create(username=name, admin_level=min(index + 1, 3), is_super=int(index == 3), created_at="x")
        cls.category = ForumCategory.objects.create(slug="scope-test", name="测试")

    def setUp(self):
        self.client = Client()
        self.old = timezone.now() - timedelta(days=10)
        for prefix in ("forum", "murmurs"):
            save_config(prefix, {"enabled": True, "admin_only": True, "quiet_minutes": 0}, "root")

    def make_posts(self, name):
        topic = ForumTopic.objects.create(category=self.category, author_username=name, title="范围测试", content="测试")
        ForumTopic.objects.filter(pk=topic.pk).update(created_at=self.old)
        murmur = Murmur.objects.create(author_username=name, content="范围测试", client_key=name, created_at=self.old.isoformat())
        return topic, murmur

    def test_all_admin_levels_get_global_heat_independent_of_viewer(self):
        pairs = [(name, *self.make_posts(name)) for name in self.names]
        topics = {row["id"]: row for row in self.client.get("/api/forum/topics").json()["items"]}
        murmurs = {row["id"]: row for row in self.client.get("/api/murmurs").json()["items"]}
        for name, topic, murmur in pairs:
            expected = name != "scope_member"
            self.assertEqual(topics[topic.pk]["display_views"] > topics[topic.pk]["views"], expected)
            self.assertEqual(murmurs[murmur.pk]["display_view_count"] > murmurs[murmur.pk]["view_count"], expected)
            detail = self.client.get(f"/api/forum/topics/{topic.pk}").json()["topic"]
            self.assertEqual(detail["display_views"] > detail["views"], expected)
            detail = self.client.get(f"/api/murmurs/{murmur.pk}").json()["item"]
            self.assertEqual(detail["display_view_count"] > detail["view_count"], expected)
            profile = self.client.get(f"/api/forum/users/{name}").json()["profile"]["topics"][0]
            self.assertEqual(profile["display_views"] > profile["views"], expected)
            topic.refresh_from_db(); murmur.refresh_from_db()
            self.assertLessEqual(topic.views, 1)
            self.assertLessEqual(murmur.view_count, 1)

    def test_removing_scope_restores_global_curve_for_normal_authors(self):
        topic, murmur = self.make_posts("scope_member")
        for prefix in ("forum", "murmurs"):
            save_config(prefix, {"admin_only": False}, "root")
        self.assertGreater(self.client.get("/api/forum/topics").json()["items"][0]["display_views"], 100)
        self.assertGreater(self.client.get("/api/murmurs").json()["items"][0]["display_view_count"], 100)

    def test_scope_persists_and_applies_to_global_frozen_values(self):
        config = save_config("forum", {"enabled": False, "frozen_at": timezone.now().isoformat()}, "root")
        self.assertTrue(config["admin_only"])
        scoped = author_config(config, "scope_member")
        self.assertEqual(display_counts(4, 2, self.old, 1, scoped), (4, 2))
        self.assertEqual(author_config(config, "scope_lv1"), config)
        with self.assertNumQueries(1):
            admins = admin_authors(config, self.names)
            for name in self.names:
                author_config(config, name, admins)
        save_config("forum", {"admin_only": False}, "root")
        self.assertFalse(get_config("forum")["admin_only"])
        self.assertTrue(get_config("murmurs")["admin_only"])

    def test_explicit_post_overrides_remain_independent(self):
        topic, murmur = self.make_posts("scope_member")
        ForumDisplayOverride.objects.create(topic=topic, enabled=True, target_views=500, grow_days=1)
        MurmurDisplayOverride.objects.create(murmur=murmur, enabled=True, target_views=500, grow_days=1)
        self.assertGreater(self.client.get("/api/forum/topics").json()["items"][0]["display_views"], 100)
        self.assertGreater(self.client.get("/api/murmurs").json()["items"][0]["display_view_count"], 100)

    def test_scope_setting_validation_and_permissions(self):
        for app in ("forum", "murmurs"):
            endpoint = f"/api/admin/{app}/heat/settings"
            self.assertEqual(self.client.post(endpoint, {"admin_only": True}, content_type="application/json").status_code, 401)
            session = self.client.session
            session.update({"admin_username": "scope_lv1", "admin_level": 1})
            session.save()
            self.assertEqual(self.client.post(endpoint, {"admin_only": True}, content_type="application/json").status_code, 403)
            session = self.client.session
            session.update({"admin_level": 3})
            session.save()
            self.assertEqual(self.client.post(endpoint, {"admin_only": "true"}, content_type="application/json").status_code, 400)
            response = self.client.post(endpoint, {"admin_only": False}, content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["settings"]["admin_only"])
            self.client = Client()
