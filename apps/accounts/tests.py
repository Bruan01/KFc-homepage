import hashlib
import re
import time

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.test import TestCase, override_settings

from apps.points.models import PointAccount, PointLedger
from .models import AdminAccount, AdminRegisterToken, EmailVerificationCode, LegacySession, User


def legacy_hash(password: str, *, iterations: int = 240000) -> str:
    salt = bytes.fromhex("00112233445566778899aabbccddeeff")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


class PasswordCompatibilityTests(TestCase):
    def test_legacy_hex_hash_is_accepted_and_upgraded_on_user_check(self):
        user = User.objects.create(
            username="legacy-user",
            password=legacy_hash("secret-pass"),
            email="legacy@example.com",
            created_at="2026-08-01T00:00:00+00:00",
        )
        self.assertTrue(user.check_password("secret-pass"))
        user.refresh_from_db()
        self.assertTrue(check_password("secret-pass", user.password))
        self.assertNotEqual(len(user.password.split("$", 3)[2]), 32)

    def test_new_password_uses_django_standard_encoding(self):
        encoded = make_password("new-password")
        algorithm, _iterations, salt, _digest = encoded.split("$", 3)
        self.assertEqual(algorithm, "pbkdf2_sha256")
        self.assertFalse(len(salt) == 32 and all(ch in "0123456789abcdef" for ch in salt))
        self.assertTrue(check_password("new-password", encoded))


class FailingEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise RuntimeError("smtp down")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="KFlow <test@example.com>",
)
class AuthenticationAPITests(TestCase):
    def setUp(self):
        mail.outbox.clear()

    def post_json(self, path, payload):
        return self.client.post(path, payload, content_type="application/json")

    def issue_code(self, email, purpose):
        response = self.post_json("/api/user/verification-code", {"email": email, "purpose": purpose})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(mail.outbox)
        match = re.search(r"(\d{6})", mail.outbox[-1].subject)
        self.assertIsNotNone(match)
        return match.group(1)

    def register_user(self, username="alice", email="alice@example.com", password="password123", invite=""):
        code = self.issue_code(email, "register")
        payload = {"username": username, "email": email, "password": password, "code": code}
        if invite:
            payload["inviteCode"] = invite
        return self.post_json("/api/user/register", payload)

    def test_registration_and_all_three_login_methods(self):
        response = self.register_user()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["ok"])
        self.assertIn(settings.SESSION_COOKIE_NAME, response.cookies)
        user = User.objects.get(username="alice")
        self.assertTrue(user.email_verified_at)
        self.assertTrue(user.check_password("password123"))
        account = PointAccount.objects.get(user=user)
        self.assertEqual(account.balance, 22)
        self.assertEqual(PointLedger.objects.filter(user=user).count(), 2)

        self.post_json("/api/user/logout", {})
        response = self.post_json("/api/user/login", {
            "method": "username_password", "username": "alice", "password": "password123"
        })
        self.assertEqual(response.status_code, 200, response.content)

        self.post_json("/api/user/logout", {})
        response = self.post_json("/api/user/login", {
            "method": "email_password", "email": "alice@example.com", "password": "password123"
        })
        self.assertEqual(response.status_code, 200, response.content)

        self.post_json("/api/user/logout", {})
        code = self.issue_code("alice@example.com", "login")
        response = self.post_json("/api/user/login", {
            "method": "email_code", "email": "alice@example.com", "code": code
        })
        self.assertEqual(response.status_code, 200, response.content)

    def test_invite_registration_grants_admin_context(self):
        invite = AdminRegisterToken.objects.create(
            token="invite-token",
            created_by="admin",
            created_at="2026-08-01T00:00:00+00:00",
            admin_level=2,
        )
        response = self.register_user("builder", "builder@example.com", invite=invite.token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_admin"])
        self.assertEqual(response.json()["admin_level"], 2)
        self.assertIn(settings.ADMIN_SESSION_COOKIE, response.cookies)
        self.assertTrue(AdminAccount.objects.filter(username="builder", admin_level=2).exists())
        invite.refresh_from_db()
        self.assertIsNotNone(invite.used_by_admin_id)

        response = self.client.get("/api/admin/me")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["loggedIn"])
        self.assertEqual(response.json()["adminLevel"], 2)

    def test_default_admin_can_login_without_user_row(self):
        response = self.post_json("/api/admin/login", {
            "username": settings.ADMIN_USERNAME,
            "password": settings.ADMIN_PASSWORD,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_super"])
        self.assertIn(settings.ADMIN_SESSION_COOKIE, response.cookies)
        response = self.client.get("/api/account/me")
        self.assertEqual(response.json()["role"], "admin")
        self.assertTrue(response.json()["isSuper"])

    def test_legacy_user_session_is_upgraded(self):
        user = User.objects.create(
            username="session-user",
            password=make_password("password123"),
            email="session@example.com",
            email_verified_at="2026-08-01T00:00:00+00:00",
            created_at="2026-08-01T00:00:00+00:00",
        )
        LegacySession.objects.create(
            token="legacy-token",
            role="user",
            user=user,
            username=user.username,
            exp=time.time() + 3600,
            created_at="2026-08-01T00:00:00+00:00",
            updated_at="2026-08-01T00:00:00+00:00",
        )
        self.client.cookies[settings.SESSION_COOKIE_NAME] = "legacy-token"
        response = self.client.get("/api/user/me")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["loggedIn"])
        self.assertFalse(LegacySession.objects.filter(token="legacy-token").exists())
        self.assertNotEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value, "legacy-token")

    def test_wrong_code_is_invalidated_after_five_attempts(self):
        code = self.issue_code("attempts@example.com", "register")
        wrong = "000000" if code != "000000" else "999999"
        payload = {
            "username": "attempt-user",
            "email": "attempts@example.com",
            "password": "password123",
            "code": wrong,
        }
        for _ in range(5):
            response = self.post_json("/api/user/register", payload)
            self.assertEqual(response.status_code, 400)
        payload["code"] = code
        response = self.post_json("/api/user/register", payload)
        self.assertEqual(response.status_code, 400)

    def test_admin_tokens_support_get_and_post_on_same_path(self):
        self.post_json("/api/admin/login", {
            "username": settings.ADMIN_USERNAME,
            "password": settings.ADMIN_PASSWORD,
        })
        response = self.post_json("/api/admin/tokens", {"admin_level": 2})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["admin_level"], 2)
        response = self.client.get("/api/admin/tokens")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)

    def test_invalid_invite_does_not_consume_registration_code(self):
        code = self.issue_code("invite-fail@example.com", "register")
        response = self.post_json("/api/user/register", {
            "username": "invite-fail",
            "email": "invite-fail@example.com",
            "password": "password123",
            "code": code,
            "inviteCode": "missing-token",
        })
        self.assertEqual(response.status_code, 400)
        record = EmailVerificationCode.objects.get(email="invite-fail@example.com", purpose="register")
        self.assertIsNone(record.used_at)

    def test_unverified_legacy_account_is_upgraded_without_changing_id(self):
        user = User.objects.create(
            username="legacy-owned",
            password="old-password",
            email="",
            email_verified_at=None,
            created_at="2025-01-01T00:00:00+00:00",
        )
        original_id = user.pk
        code = self.issue_code("claimed@example.com", "register")
        response = self.post_json("/api/user/register", {
            "username": "legacy-owned",
            "email": "claimed@example.com",
            "password": "old-password",
            "code": code,
        })
        self.assertEqual(response.status_code, 200, response.content)
        user.refresh_from_db()
        self.assertEqual(user.pk, original_id)
        self.assertEqual(user.email, "claimed@example.com")
        self.assertTrue(user.check_password("old-password"))

    def test_legacy_account_cannot_be_claimed_with_wrong_password(self):
        User.objects.create(
            username="owned", password="real-password", email="",
            email_verified_at=None, created_at="2025-01-01T00:00:00+00:00",
        )
        code = self.issue_code("owner@example.com", "register")
        response = self.post_json("/api/user/register", {
            "username": "owned", "email": "owner@example.com",
            "password": "wrong-password", "code": code,
        })
        self.assertEqual(response.status_code, 409)

    def test_email_bind_requires_password_and_consumes_bind_code(self):
        user = User(username="binder", email="", created_at="2025-01-01T00:00:00+00:00")
        user.set_password("password123")
        user.save()
        login_response = self.post_json("/api/user/login", {
            "method": "username_password", "username": "binder", "password": "password123"
        })
        self.assertEqual(login_response.status_code, 403)
        user.email_verified_at = "2025-01-01T00:00:00+00:00"
        user.save(update_fields=["email_verified_at"])
        login_response = self.post_json("/api/user/login", {
            "method": "username_password", "username": "binder", "password": "password123"
        })
        self.assertEqual(login_response.status_code, 200)
        code = self.issue_code("bound@example.com", "bind")
        response = self.post_json("/api/user/email/bind", {
            "email": "bound@example.com", "code": code, "currentPassword": "password123"
        })
        self.assertEqual(response.status_code, 200, response.content)
        user.refresh_from_db()
        self.assertEqual(user.email, "bound@example.com")

    def test_verification_code_cooldown_and_unknown_login_email(self):
        self.issue_code("cooldown@example.com", "register")
        response = self.post_json("/api/user/verification-code", {
            "email": "cooldown@example.com", "purpose": "register"
        })
        self.assertEqual(response.status_code, 429)
        before = len(mail.outbox)
        response = self.post_json("/api/user/verification-code", {
            "email": "missing@example.com", "purpose": "login"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), before)

    @override_settings(EMAIL_BACKEND="apps.accounts.tests.FailingEmailBackend")
    def test_delivery_failure_invalidates_created_code(self):
        response = self.post_json("/api/user/verification-code", {
            "email": "broken@example.com", "purpose": "register"
        })
        self.assertEqual(response.status_code, 503)
        record = EmailVerificationCode.objects.get(email="broken@example.com")
        self.assertIsNotNone(record.used_at)

    def test_legacy_admin_register_endpoint_remains_gone(self):
        response = self.post_json("/api/admin/register", {})
        self.assertEqual(response.status_code, 410)
