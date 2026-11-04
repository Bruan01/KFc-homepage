"""后台系统邮箱设置的接口测试。"""
from __future__ import annotations

import json

from django.core import mail
from django.test import Client, TestCase, override_settings

from apps.catalog.models import SystemSetting

from . import mailing
from .models import AdminAccount, EmailDelivery, User


def admin_client(level: int = 3, super_admin: bool = False) -> Client:
    client = Client()
    session = client.session
    session["admin_username"] = "root"
    session["admin_level"] = level
    session["admin_is_super"] = super_admin or level >= 3
    session.save()
    return client


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MailAdminApiTests(TestCase):
    def setUp(self):
        AdminAccount.objects.create(
            username="ops",
            password_hash="x",
            email="ops@example.com",
            created_at="2026-11-01T00:00:00+00:00",
            admin_level=3,
            is_super=1,
        )

    def test_requires_admin_level_three(self):
        anonymous = Client().get("/api/admin/mail/settings")
        self.assertEqual(anonymous.status_code, 401)

        low = admin_client(level=2, super_admin=False)
        denied = low.get("/api/admin/mail/settings")
        self.assertEqual(denied.status_code, 403)

    def test_get_returns_config_events_and_stats(self):
        response = admin_client().get("/api/admin/mail/settings")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("config", data)
        self.assertIn("events", data)
        self.assertIn("stats", data)
        self.assertEqual(data["config"]["source"], "none")
        self.assertFalse(data["config"]["passwordSet"])
        self.assertTrue(data["events"]["enabled"])
        self.assertEqual(data["stats"]["total"], 0)

    def test_save_config_encrypts_password_and_hides_it(self):
        payload = {
            "config": {
                "host": "smtp.example.com",
                "port": 465,
                "username": "no-reply@example.com",
                "password": "super-secret",
                "fromEmail": "KFlow <no-reply@example.com>",
                "useTls": False,
                "useSsl": True,
                "timeout": 12,
            }
        }
        response = admin_client().post(
            "/api/admin/mail/settings",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["config"]["passwordSet"])
        self.assertNotIn("super-secret", response.content.decode("utf-8"))
        self.assertEqual(data["config"]["source"], "database")

        stored = SystemSetting.objects.get(pk=mailing.KEY_PASSWORD).setting_value
        self.assertNotEqual(stored, "super-secret")
        self.assertEqual(mailing.decrypt_secret(stored), "super-secret")

    def test_blank_password_keeps_existing_secret(self):
        admin = admin_client()
        admin.post(
            "/api/admin/mail/settings",
            data=json.dumps({"config": {"host": "smtp.example.com", "password": "first-pass"}}),
            content_type="application/json",
        )
        admin.post(
            "/api/admin/mail/settings",
            data=json.dumps({"config": {"host": "smtp.example.com", "username": "u@example.com"}}),
            content_type="application/json",
        )
        self.assertEqual(mailing.load_config().password, "first-pass")

    def test_rejects_conflicting_tls_and_ssl(self):
        response = admin_client().post(
            "/api/admin/mail/settings",
            data=json.dumps({"config": {"host": "smtp.example.com", "useTls": True, "useSsl": True}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("STARTTLS", response.content.decode("utf-8"))

    def test_admin_directory_lists_admins_with_email_flag(self):
        data = json.loads(admin_client().get("/api/admin/mail/settings").content)
        directory = data["events"]["adminDirectory"]
        self.assertEqual([item["username"] for item in directory], ["ops"])
        self.assertTrue(directory[0]["hasEmail"])
        # 默认篮子是空的：必须手动把管理员拖进去
        self.assertEqual(data["events"]["recipients"], [])
        self.assertEqual(data["events"]["resolvedRecipients"], [])

    def test_unbound_admin_stays_in_directory_but_cannot_be_picked(self):
        AdminAccount.objects.create(
            username="no-mail",
            password_hash="x",
            email="",
            created_at="2026-11-01T00:00:00+00:00",
            admin_level=1,
        )
        data = json.loads(admin_client().get("/api/admin/mail/settings").content)
        directory = {item["username"]: item for item in data["events"]["adminDirectory"]}
        self.assertIn("no-mail", directory)
        self.assertFalse(directory["no-mail"]["hasEmail"])

        response = admin_client().post(
            "/api/admin/mail/settings",
            data=json.dumps({"events": {"recipients": ["no-mail", "ops"], "emails": []}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["events"]["recipients"], ["ops"])

    def test_save_event_settings_with_recipients(self):
        payload = {
            "events": {
                "enabled": False,
                "recipients": ["ops"],
                "emails": ["extra@example.com", "ops@example.com"],
            },
        }
        response = admin_client().post(
            "/api/admin/mail/settings",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertFalse(data["events"]["enabled"])
        self.assertEqual(data["events"]["recipients"], ["ops"])
        self.assertEqual(data["events"]["emails"], ["extra@example.com", "ops@example.com"])
        self.assertEqual(data["events"]["resolvedRecipients"], ["ops@example.com", "extra@example.com"])

    def test_legacy_admins_flag_still_expands_to_everyone(self):
        SystemSetting.objects.update_or_create(
            setting_key=mailing.KEY_EVENT_REGISTER,
            defaults={
                "setting_value": json.dumps({"enabled": True, "admins": True, "emails": []}),
                "updated_at": "2026-11-01T00:00:00+00:00",
            },
        )
        data = json.loads(admin_client().get("/api/admin/mail/settings").content)
        self.assertTrue(data["events"]["selectAll"])
        self.assertIn("ops@example.com", data["events"]["resolvedRecipients"])

    def test_test_mail_sends_and_logs(self):
        response = admin_client().post(
            "/api/admin/mail/test",
            data=json.dumps({"to": "ops@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("测试邮件", mail.outbox[0].body)

        record = EmailDelivery.objects.latest("id")
        self.assertEqual(record.status, "sent")
        self.assertEqual(record.event, "manual_test")
        self.assertEqual(record.to_email, "ops@example.com")

    def test_delivery_list_supports_status_filter_and_paging(self):
        for index in range(3):
            EmailDelivery.objects.create(
                category="verification",
                event="verification_register",
                to_email="a@example.com",
                subject=f"code {index}",
                status="sent" if index < 2 else "failed",
                created_at="2026-11-04T10:00:00+00:00",
            )
        response = admin_client().get("/api/admin/mail/deliveries?status=failed")
        data = json.loads(response.content)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["status"], "failed")
        self.assertEqual(data["items"][0]["eventLabel"], "注册验证码")

    def test_bind_admin_email_for_notifications(self):
        response = admin_client().post(
            "/api/admin/mail/admin-email",
            data=json.dumps({"username": "ops", "email": "Ops@Example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AdminAccount.objects.get(username="ops").email, "ops@example.com")

    def test_bind_admin_email_rejects_duplicate(self):
        AdminAccount.objects.create(
            username="second",
            password_hash="x",
            email="taken@example.com",
            created_at="2026-11-01T00:00:00+00:00",
            admin_level=1,
        )
        response = admin_client().post(
            "/api/admin/mail/admin-email",
            data=json.dumps({"username": "ops", "email": "taken@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_bind_admin_email_rejects_unknown_admin(self):
        response = admin_client().post(
            "/api/admin/mail/admin-email",
            data=json.dumps({"username": "nobody", "email": "x@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_retry_creates_a_new_delivery(self):
        record = EmailDelivery.objects.create(
            category="event",
            event="user_registered",
            to_email="ops@example.com",
            subject="新用户注册",
            status="failed",
            error="timeout",
            created_at="2026-11-04T10:00:00+00:00",
        )
        response = admin_client().post(f"/api/admin/mail/deliveries/{record.id}/retry")
        self.assertEqual(response.status_code, 200)
        latest = EmailDelivery.objects.latest("id")
        self.assertEqual(latest.event, "manual_retry")
        self.assertEqual(latest.status, "sent")
        self.assertIn("重发", latest.subject)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MailEventNotificationTests(TestCase):
    def setUp(self):
        AdminAccount.objects.create(
            username="ops",
            password_hash="x",
            email="ops@example.com",
            created_at="2026-11-01T00:00:00+00:00",
            admin_level=3,
        )

    def test_disabled_event_sends_nothing(self):
        mailing.save_event_settings({"enabled": False, "recipients": ["ops"], "emails": []}, "root")
        user = User.objects.create(
            username="newbie",
            email="newbie@example.com",
            created_at=mailing.now_iso(),
        )
        self.assertEqual(mailing.notify_user_registered(user), [])
        self.assertEqual(EmailDelivery.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_selected_admin_is_resolved(self):
        mailing.save_event_settings({"enabled": True, "recipients": ["ops"], "emails": []}, "root")
        self.assertEqual(mailing.resolve_recipients(), ["ops@example.com"])

    def test_unselected_admin_is_skipped(self):
        mailing.save_event_settings(
            {"enabled": True, "recipients": [], "emails": ["extra@example.com"]},
            "root",
        )
        self.assertEqual(mailing.resolve_recipients(), ["extra@example.com"])

    def test_stats_counts_by_status(self):
        EmailDelivery.objects.create(category="verification", event="verification_login", to_email="a@b.com",
                                     subject="x", status="sent", created_at=mailing.now_iso())
        EmailDelivery.objects.create(category="event", event="user_registered", to_email="a@b.com",
                                     subject="x", status="failed", error="boom", created_at=mailing.now_iso())
        stats = mailing.delivery_stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["today"], 2)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["successRate"], 50.0)
