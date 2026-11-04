"""换绑邮箱与忘记密码的接口测试。"""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import EmailVerificationCode, User


def make_user(username="kieran", email="old@example.com", password="oldpassword1"):
    now = timezone.now().isoformat()
    user = User(
        username=username,
        email=email,
        email_verified_at=now if email else None,
        created_at=now,
    )
    user.set_password(password)
    user.save()
    return user


def issue_code(email, purpose, code="123456"):
    now = timezone.now()
    EmailVerificationCode.objects.filter(email=email, purpose=purpose).delete()
    return EmailVerificationCode.objects.create(
        email=email,
        purpose=purpose,
        code_hash=make_password(code),
        request_ip="127.0.0.1",
        attempt_count=0,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=10)).isoformat(),
    )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailRebindTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = Client()
        self.client.force_login(self.user)

    def post_bind(self, **overrides):
        payload = {
            "email": "new@example.com",
            "code": "123456",
            "currentPassword": "oldpassword1",
        }
        payload.update(overrides)
        return self.client.post(
            "/api/user/email/bind",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_rebind_replaces_email(self):
        issue_code("new@example.com", "bind")
        response = self.post_bind()
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["rebound"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")

    def test_rebind_notifies_old_address(self):
        issue_code("new@example.com", "bind")
        with patch("apps.accounts.mailing._run_async", side_effect=lambda fn, **kw: fn(**kw)):
            response = self.post_bind()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("old@example.com", mail.outbox[0].to)
        self.assertIn("new@example.com", mail.outbox[0].body)

    def test_rebind_keeps_current_session(self):
        """换绑不该把人踢下线：历史实现里 set_password 会改变 session auth hash。"""
        issue_code("new@example.com", "bind")
        self.assertEqual(self.post_bind().status_code, 200)
        me = self.client.get("/api/account/settings")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(json.loads(me.content)["email"], "new@example.com")

    def test_same_email_is_rejected(self):
        issue_code("old@example.com", "bind")
        response = self.post_bind(email="old@example.com")
        self.assertEqual(response.status_code, 409)

    def test_wrong_password_is_rejected(self):
        issue_code("new@example.com", "bind")
        response = self.post_bind(currentPassword="wrong-password")
        self.assertEqual(response.status_code, 401)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@example.com")

    def test_email_taken_by_someone_else(self):
        make_user(username="other", email="taken@example.com")
        issue_code("taken@example.com", "bind")
        response = self.post_bind(email="taken@example.com")
        self.assertEqual(response.status_code, 409)

    def test_first_time_bind_reports_not_rebound(self):
        user = make_user(username="fresh", email="")
        client = Client()
        client.force_login(user)
        issue_code("first@example.com", "bind")
        response = client.post(
            "/api/user/email/bind",
            data=json.dumps(
                {"email": "first@example.com", "code": "123456", "currentPassword": "oldpassword1"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json.loads(response.content)["rebound"])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = make_user(email="kieran@example.com", password="oldpassword1")

    def post_reset(self, **overrides):
        payload = {
            "email": "kieran@example.com",
            "code": "123456",
            "newPassword": "brandnewpass9",
            "confirmPassword": "brandnewpass9",
        }
        payload.update(overrides)
        return Client().post(
            "/api/user/password/reset",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_reset_changes_password(self):
        issue_code("kieran@example.com", "reset")
        response = self.post_reset()
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brandnewpass9"))

    def test_wrong_code_rejected(self):
        issue_code("kieran@example.com", "reset")
        response = self.post_reset(code="000000")
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("oldpassword1"))

    def test_unknown_email_does_not_leak(self):
        response = self.post_reset(email="nobody@example.com")
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid or expired", response.content.decode("utf-8"))

    def test_short_password_rejected(self):
        issue_code("kieran@example.com", "reset")
        response = self.post_reset(newPassword="123", confirmPassword="123")
        self.assertEqual(response.status_code, 400)

    def test_mismatched_confirmation_rejected(self):
        issue_code("kieran@example.com", "reset")
        response = self.post_reset(confirmPassword="different-pass9")
        self.assertEqual(response.status_code, 400)

    def test_code_is_single_use(self):
        issue_code("kieran@example.com", "reset")
        self.assertEqual(self.post_reset().status_code, 200)
        second = self.post_reset(newPassword="anotherpass9", confirmPassword="anotherpass9")
        self.assertEqual(second.status_code, 400)


class ResetCodePurposeTests(TestCase):
    def test_reset_code_is_silent_for_unknown_email(self):
        """未注册邮箱不发码，也不报错，避免被用来探测账号。"""
        from .services import issue_verification_code

        self.assertFalse(issue_verification_code("nobody@example.com", "reset", "127.0.0.1"))
        self.assertEqual(EmailVerificationCode.objects.count(), 0)

    def test_reset_purpose_is_accepted(self):
        make_user(email="known@example.com")
        from .services import issue_verification_code

        with patch("apps.accounts.mailing._run_async", side_effect=lambda fn, **kw: fn(**kw)):
            self.assertTrue(issue_verification_code("known@example.com", "reset", "127.0.0.1"))
        row = EmailVerificationCode.objects.get(email="known@example.com", purpose="reset")
        self.assertTrue(row.code_hash.startswith("pbkdf2"))
