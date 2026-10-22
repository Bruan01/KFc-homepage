from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.sessions.models import Session
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.murmurs.models import Murmur
from apps.points.models import PointAccount, PointLedger
from .models import AdminAccount, AdminRegisterToken, EmailVerificationCode, OfficialCommunitySettings, User, UserFollow
from .services import AccountError


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ExistingAccountActivationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "activation-password-2026"
        cls.alice = User.objects.create_user(username="existing_alice", password=cls.password, email="alice@example.com", email_verified_at="yes", created_at="2026-01-01", display_name="小 K 测试", bio="原有简介")
        cls.bob = User.objects.create_user(username="existing_bob", password=cls.password, email="bob@example.com", email_verified_at="yes", created_at="2026-01-01")

    def setUp(self):
        self.client.force_login(self.alice)

    def code(self, level=3, **extra):
        return AdminRegisterToken.objects.create(token=f"activation-{AdminRegisterToken.objects.count():054d}", admin_level=level, created_by="issuer", created_at="2026-01-01", **extra)

    def activate(self, code, password=None, client=None, **extra):
        return (client or self.client).post("/api/user/activate-admin", {"activation_code": code, "password": self.password if password is None else password, **extra}, content_type="application/json")

    def test_existing_official_account_activates_without_replacing_profile_content_points_or_followers(self):
        OfficialCommunitySettings.objects.create(account=self.alice)
        original_pk = self.alice.pk
        post = Murmur.objects.create(author_username=self.alice.username, content="原有内容", client_key="old-content")
        UserFollow.objects.create(follower=self.bob, following=self.alice, created_at="x")
        PointAccount.objects.create(user=self.alice, balance=123, updated_at="x")
        token = self.code(3)
        response = self.activate(token.token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["adminLevel"], 3)
        self.assertFalse(response.json()["isSuper"])
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.pk, original_pk)
        self.assertEqual(self.alice.display_name, "小 K 测试")
        self.assertEqual(self.alice.bio, "原有简介")
        self.assertTrue(Murmur.objects.filter(pk=post.pk, author_username=self.alice.username).exists())
        self.assertTrue(UserFollow.objects.filter(follower=self.bob, following=self.alice).exists())
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 123)
        self.assertFalse(PointLedger.objects.filter(user=self.alice).exists())
        token.refresh_from_db(); admin = AdminAccount.objects.get(username=self.alice.username)
        self.assertEqual(token.used_by_admin_id, admin.pk)
        self.assertTrue(token.used_at)
        self.assertEqual(admin.created_by, "issuer")
        self.assertFalse(admin.is_super)
        self.assertEqual(OfficialCommunitySettings.objects.get().account_id, original_pk)

    def test_session_rotates_and_permissions_are_immediate_without_super_admin_access(self):
        previous_key = self.client.session.session_key
        response = self.activate(self.code().token)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.client.session.session_key, previous_key)
        self.assertFalse(Session.objects.filter(session_key=previous_key).exists())
        self.assertEqual(response.cookies[settings.ADMIN_SESSION_COOKIE].value, self.client.session.session_key)
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME].value, self.client.session.session_key)
        self.assertEqual(self.client.get("/api/admin/me").json()["adminLevel"], 3)
        self.assertEqual(self.client.get("/api/account/me").json()["role"], "admin")
        self.assertEqual(self.client.get("/api/forum/users/me/profile").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/community-ai/settings").status_code, 403)
        item = next(row for row in self.client.get("/api/admin/users").json()["items"] if row["id"] == self.alice.pk)
        self.assertEqual(item["admin_level"], 3)
        self.assertFalse(item["is_super"])

    def test_password_failure_or_invalid_code_has_no_side_effects(self):
        token = self.code()
        self.assertEqual(self.activate(token.token, password="wrong").status_code, 403)
        self.assertEqual(self.activate("missing-code").status_code, 400)
        self.assertFalse(AdminAccount.objects.filter(username=self.alice.username).exists())
        token.refresh_from_db(); self.assertIsNone(token.used_by_admin_id); self.assertIsNone(token.used_at)

    def test_guest_csrf_and_bad_inputs_are_rejected(self):
        token = self.code()
        self.assertEqual(self.activate(token.token, client=Client()).status_code, 401)
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.alice)
        self.assertEqual(self.activate(token.token, client=strict).status_code, 403)
        csrf = strict.get("/account").cookies["csrftoken"].value
        response = strict.post("/api/user/activate-admin", {"activation_code": token.token, "password": self.password}, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        for payload in ({}, [], {"activation_code": True}, {"activation_code": "x", "password": []}, {"activation_code": "x" * 257, "password": self.password}):
            self.assertEqual(self.client.post("/api/user/activate-admin", payload, content_type="application/json").status_code, 400)

    def test_target_and_level_cannot_be_overridden_in_request(self):
        token = self.code(1)
        response = self.activate(token.token, username=self.bob.username, user_id=self.bob.pk, admin_level=3, is_super=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], self.alice.username)
        self.assertEqual(response.json()["adminLevel"], 1)
        self.assertFalse(AdminAccount.objects.filter(username=self.bob.username).exists())

    def test_retry_by_same_account_is_safe_but_another_account_cannot_reuse_code(self):
        token = self.code()
        first = self.activate(token.token)
        second = self.activate(token.token)
        self.assertEqual(first.status_code, 200); self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()["replayed"]); self.assertTrue(second.json()["replayed"])
        self.assertEqual(AdminAccount.objects.filter(username=self.alice.username).count(), 1)
        bob = Client(); bob.force_login(self.bob)
        self.assertEqual(self.activate(token.token, client=bob).status_code, 400)
        self.assertFalse(AdminAccount.objects.filter(username=self.bob.username).exists())

    def test_existing_admin_can_upgrade_and_lower_or_equal_codes_are_not_consumed(self):
        admin = AdminAccount.objects.create(username=self.alice.username, admin_level=1, password_hash=make_password("old-admin-password"), email=self.alice.email, created_at="x", created_by="original")
        first = self.code(2)
        self.assertEqual(self.activate(first.token).json()["adminLevel"], 2)
        for level in (1, 2):
            token = self.code(level)
            self.assertEqual(self.activate(token.token).status_code, 400)
            token.refresh_from_db(); self.assertIsNone(token.used_by_admin_id)
        last = self.code(3)
        self.assertEqual(self.activate(last.token).json()["adminLevel"], 3)
        self.assertEqual(self.activate(first.token).json()["adminLevel"], 3)
        admin.refresh_from_db(); self.assertEqual(admin.created_by, "original")
        self.assertEqual(admin.admin_level, 3)
        self.client.logout()
        response = self.client.post("/api/admin/login", {"username": self.alice.username, "password": self.password}, content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_claim_failure_rolls_back_admin_creation_and_token_consumption(self):
        token = self.code()
        with patch("apps.accounts.activation.claim_admin_code", side_effect=AccountError("冲突", status=409)):
            self.assertEqual(self.activate(token.token).status_code, 409)
        self.assertFalse(AdminAccount.objects.filter(username=self.alice.username).exists())
        token.refresh_from_db(); self.assertIsNone(token.used_by_admin_id)
        self.assertEqual(self.client.get("/api/account/me").json()["role"], "user")

    def test_invalid_token_level_and_inconsistent_used_record_are_rejected(self):
        for level in (0, 4):
            self.assertEqual(self.activate(self.code(level).token).status_code, 400)
        self.assertEqual(self.activate(self.code(3, used_at="2026-01-01").token).status_code, 400)
        self.assertFalse(AdminAccount.objects.filter(username=self.alice.username).exists())

    def test_unverified_system_and_super_admin_accounts_do_not_consume_code(self):
        token = self.code()
        User.objects.filter(pk=self.alice.pk).update(email_verified_at=None)
        self.assertEqual(self.activate(token.token).status_code, 400)
        User.objects.filter(pk=self.alice.pk).update(email_verified_at="yes", is_system_generated=True)
        self.assertEqual(self.activate(token.token).status_code, 403)
        User.objects.filter(pk=self.alice.pk).update(is_system_generated=False)
        AdminAccount.objects.create(username=self.alice.username, is_super=1, admin_level=3, created_at="x")
        self.assertEqual(self.activate(token.token).status_code, 400)
        token.refresh_from_db(); self.assertIsNone(token.used_by_admin_id)

    def test_code_is_shared_with_existing_registration_flow_and_cannot_be_used_twice(self):
        token = self.code()
        new_email = "new@example.com"
        record = EmailVerificationCode.objects.create(email=new_email, purpose="register", code_hash=make_password("123456"), created_at=timezone.now().isoformat(), expires_at=(timezone.now() + timedelta(minutes=10)).isoformat())
        self.assertEqual(self.activate(token.token).status_code, 200)
        guest = Client()
        response = guest.post("/api/user/register", {"username": "new_member", "email": new_email, "password": self.password, "code": "123456", "inviteCode": token.token}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="new_member").exists())
        record.refresh_from_db(); self.assertIsNone(record.used_at)

    def test_legacy_blank_unused_timestamp_is_accepted(self):
        token = self.code(3, used_at="")
        self.assertEqual(self.activate(token.token).status_code, 200)

    @override_settings(PASSWORD_HASHERS=["apps.accounts.hashers.LegacyHexPBKDF2PasswordHasher"])
    def test_legacy_password_upgrade_preserves_authentication_after_activation(self):
        from .tests import legacy_hash
        User.objects.filter(pk=self.alice.pk).update(password=legacy_hash(self.password))
        self.alice.refresh_from_db(); self.client.force_login(self.alice)
        response = self.activate(self.code().token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/forum/users/me/profile").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/me").json()["adminLevel"], 3)

    def test_unusable_password_cannot_be_used_as_confirmation(self):
        token = self.code()
        self.alice.set_unusable_password(); self.alice.save(update_fields=["password"])
        self.client.force_login(self.alice)
        self.assertEqual(self.activate(token.token, password=self.alice.password).status_code, 400)
        token.refresh_from_db(); self.assertIsNone(token.used_by_admin_id)

    def test_busy_database_returns_retryable_conflict_without_consuming_code(self):
        token = self.code()
        with patch("apps.accounts.views.activate_existing_user", side_effect=OperationalError("database is locked")):
            self.assertEqual(self.activate(token.token).status_code, 409)
        token.refresh_from_db(); self.assertIsNone(token.used_by_admin_id)
        self.assertFalse(AdminAccount.objects.filter(username=self.alice.username).exists())
