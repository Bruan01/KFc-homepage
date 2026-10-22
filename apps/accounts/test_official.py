import json
import importlib
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase

from apps.murmurs.models import MurmurBlock
from apps.notifications.models import Notification
from .models import AdminAccount, OfficialCommunitySettings, OfficialFollowInitialization, User, UserFollow
from .official import initialize_official_follow


class OfficialCommunityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.official = User.objects.create(username="xiaok", display_name="小 K", created_at="2026-10-22")
        cls.alice = User.objects.create(username="alice", created_at="2026-10-22")
        cls.bob = User.objects.create(username="bob", created_at="2026-10-22")
        cls.virtual = User.objects.create(username="community_guest_20261001", is_system_generated=True, created_at="2026-10-22")

    def setUp(self):
        session = self.client.session
        session["admin_username"] = "root"; session["admin_is_super"] = True; session["admin_level"] = 3; session.save()

    def save_settings(self, target=8, username="xiaok", client=None):
        return (client or self.client).post("/api/admin/community/official", json.dumps({"account_username": username, "target_follower_count": target}), content_type="application/json")

    def test_configuration_reuses_official_account_and_fills_real_relationships(self):
        original_id = self.official.pk
        response = self.save_settings()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["account"]["id"], original_id)
        self.assertEqual(response.json()["settings"]["follower_count"], 8)
        for user in (self.alice, self.bob, self.virtual):
            self.assertTrue(UserFollow.objects.filter(follower=user, following=self.official).exists())
        self.assertFalse(UserFollow.objects.filter(follower=self.official, following=self.official).exists())
        self.assertEqual(User.objects.filter(username="xiaok").count(), 1)
        self.assertFalse(AdminAccount.objects.filter(username="xiaok").exists())
        self.assertEqual(Notification.objects.count(), 0)

    def test_saving_same_target_is_idempotent_and_increase_reuses_existing_system_users(self):
        self.save_settings(8)
        count = User.objects.count()
        self.assertEqual(self.save_settings(8).json()["changes"]["created_accounts"], 0)
        self.assertEqual(User.objects.count(), count)
        self.save_settings(3)
        response = self.save_settings(8)
        self.assertEqual(response.json()["changes"]["created_accounts"], 0)
        self.assertEqual(User.objects.count(), count)
        self.assertEqual(self.official.follower_edges.count(), 8)

    def test_decreasing_target_preserves_real_and_preexisting_manual_follows(self):
        UserFollow.objects.create(follower=self.virtual, following=self.official, created_at="x")
        self.save_settings(8)
        response = self.save_settings(0)
        self.assertEqual(response.json()["settings"]["follower_count"], 3)
        self.assertEqual(response.json()["settings"]["managed_follower_count"], 0)
        for user in (self.alice, self.bob, self.virtual):
            self.assertTrue(UserFollow.objects.filter(follower=user, following=self.official).exists())
        self.assertGreater(User.objects.filter(is_system_generated=True).count(), 1)

    def test_unfollow_is_not_restored_by_resync_login_or_user_save(self):
        self.save_settings(6)
        alice = Client(); alice.force_login(self.alice)
        self.assertEqual(alice.delete("/api/users/xiaok/follow").status_code, 200)
        self.alice.display_name = "Alice"; self.alice.save()
        initialize_official_follow(self.alice)
        self.save_settings(6)
        self.assertFalse(UserFollow.objects.filter(follower=self.alice, following=self.official).exists())
        self.assertTrue(OfficialFollowInitialization.objects.filter(user=self.alice, official=self.official).exists())
        self.assertEqual(self.official.follower_edges.count(), 6)
        self.assertEqual(alice.post("/api/users/xiaok/follow").status_code, 200)

    def test_new_users_and_daily_generated_accounts_default_follow_official(self):
        self.save_settings(4)
        user = User.objects.create_user(username="new_member", password="password-for-test", created_at="x")
        self.assertTrue(UserFollow.objects.filter(follower=user, following=self.official).exists())
        call_command("grow_community_members", verbosity=0)
        daily = User.objects.filter(username__startswith="community_guest_").exclude(pk=self.virtual.pk).get()
        self.assertTrue(daily.is_system_generated)
        self.assertFalse(daily.has_usable_password())
        self.assertTrue(UserFollow.objects.filter(follower=daily, following=self.official).exists())

    def test_blocks_in_both_directions_are_respected_by_backfill_and_new_user(self):
        MurmurBlock.objects.create(username="alice", blocked_username="xiaok")
        MurmurBlock.objects.create(username="xiaok", blocked_username="bob")
        MurmurBlock.objects.create(username="xiaok", blocked_username="later")
        self.save_settings(5)
        later = User.objects.create(username="later", created_at="x")
        for user in (self.alice, self.bob, later):
            self.assertFalse(UserFollow.objects.filter(follower=user, following=self.official).exists())
        self.assertEqual(self.official.follower_edges.count(), 5)

    def test_generated_accounts_cannot_login_and_public_payload_does_not_expose_internal_flag(self):
        self.save_settings(6)
        system = User.objects.filter(is_system_generated=True).exclude(pk=self.virtual.pk).first()
        self.assertFalse(system.has_usable_password())
        self.assertFalse(system.email_verified_at)
        payload = Client().get(f"/api/forum/users/{system.username}").json()["profile"]
        self.assertNotIn("is_system_generated", payload)
        self.assertNotIn("password", payload)

    def test_only_current_official_account_has_badge_and_mentions_remain_owner_scoped(self):
        self.save_settings(3)
        guest = Client()
        self.assertTrue(guest.get("/api/users/xiaok/social").json()["is_official"])
        self.assertTrue(guest.get("/api/forum/users/xiaok").json()["profile"]["is_official"])
        alice = Client(); alice.force_login(self.alice)
        self.assertTrue(next(item for item in alice.get("/api/users/mentions").json()["items"] if item["username"] == "xiaok")["is_official"])
        self.assertEqual(alice.get("/api/users/xiaok/followers").status_code, 403)
        self.save_settings(3, username="bob")
        self.assertFalse(guest.get("/api/users/xiaok/social").json()["is_official"])
        self.assertTrue(guest.get("/api/users/bob/social").json()["is_official"])

    def test_permissions_and_csrf_are_required(self):
        self.assertEqual(self.save_settings(client=Client()).status_code, 401)
        normal = Client(); normal.force_login(self.alice)
        self.assertEqual(self.save_settings(client=normal).status_code, 401)
        lower = Client(); session = lower.session
        session["admin_username"] = "lower"; session["admin_is_super"] = False; session["admin_level"] = 3; session.save()
        self.assertEqual(self.save_settings(client=lower).status_code, 403)
        strict = Client(enforce_csrf_checks=True); session = strict.session
        session["admin_username"] = "root"; session["admin_is_super"] = True; session["admin_level"] = 3; session.save()
        self.assertEqual(self.save_settings(client=strict).status_code, 403)

    def test_invalid_configuration_has_no_side_effects(self):
        count = User.objects.count()
        for target in (-1, 10001, True, "100", 1.5, None):
            self.assertEqual(self.save_settings(target).status_code, 400)
        self.assertEqual(self.save_settings(username="missing").status_code, 404)
        self.assertEqual(self.save_settings(username=self.virtual.username).status_code, 404)
        self.assertEqual(self.client.post("/api/admin/community/official", "[]", content_type="application/json").status_code, 400)
        self.assertFalse(OfficialCommunitySettings.objects.exists())
        self.assertEqual(User.objects.count(), count)

    def test_configuration_rolls_back_if_follower_creation_fails(self):
        with patch("apps.accounts.admin_community.adjust_managed_followers", side_effect=RuntimeError("simulated failure")):
            with self.assertRaises(RuntimeError):
                self.save_settings()
        self.assertFalse(OfficialCommunitySettings.objects.exists())
        self.assertFalse(UserFollow.objects.exists())
        self.assertFalse(OfficialFollowInitialization.objects.exists())

    def test_singleton_constraint_and_default_initialization_history(self):
        self.save_settings(4)
        self.assertEqual(OfficialFollowInitialization.objects.filter(user=self.alice, official=self.official).count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfficialCommunitySettings.objects.create(pk=2, account=self.official)

    def test_legacy_account_classification_keeps_verified_users_and_admins_unchanged(self):
        legacy = User.objects.create(username="community_guest_20260901", created_at="x")
        named_real = User.objects.create(username="community_guest_20260902", email="member@example.com", created_at="x")
        verified = User.objects.create(username="community_guest_20260903", email_verified_at="verified", created_at="x")
        admin = User.objects.create(username="community_guest_20260904", created_at="x")
        AdminAccount.objects.create(username=admin.username, created_at="x")
        ordinary = User.objects.create(username="community_guest_custom", created_at="x")
        migration = importlib.import_module("apps.accounts.migrations.0007_mark_legacy_community_accounts")
        migration.mark_legacy_accounts(apps, SimpleNamespace(connection=connection))
        legacy.refresh_from_db(); self.assertTrue(legacy.is_system_generated)
        for user in (named_real, verified, admin, ordinary):
            user.refresh_from_db(); self.assertFalse(user.is_system_generated)
