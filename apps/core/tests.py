# pyright: reportMissingImports=false

import json
from datetime import timedelta
from io import StringIO

from unittest.mock import patch

from django.core.management import call_command
from django.test import Client
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import LegacySession
from apps.downloads.models import UploadSession


class NewAPIProxyTests(TestCase):
    @patch("apps.core.views._newapi_get")
    def test_status_filters_sensitive_fields(self, fetch):
        fetch.return_value = (
            {
                "success": True,
                "data": {
                    "system_name": "Status",
                    "version": "v1",
                    "server_address": "http://internal.example:8579",
                    "announcements": [
                        {"type": "info", "content": "访问 http://10.0.0.1:9000"}
                    ],
                },
            },
            200,
        )

        response = self.client.get("/api/newapi/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("server_address", body["data"])
        self.assertEqual(body["data"]["announcements"][0]["content"], "访问 [地址已隐藏]")
        self.assertNotIn("10.0.0.1", response.content.decode())

    @patch("apps.core.views._newapi_get")
    def test_models_and_channels_return_public_fields_only(self, fetch):
        def response_for(path):
            if path == "/api/models":
                return {"success": True, "data": {"1": ["gpt-test"]}}, 200
            return {
                "success": True,
                "data": {
                    "items": [
                        {
                            "id": 1,
                            "name": "Channel",
                            "status": 1,
                            "models": "gpt-test,claude-test",
                            "base_url": "http://internal.example",
                            "key": "secret",
                        }
                    ]
                },
            }, 200

        fetch.side_effect = response_for

        models = self.client.get("/api/newapi/models")
        channels = self.client.get("/api/newapi/channels")

        self.assertEqual(models.json()["data"], {"models": [{"name": "gpt-test"}], "total": 1})
        channel = channels.json()["data"]["channels"][0]
        self.assertEqual(channel["model_count"], 2)
        self.assertNotIn("base_url", channel)
        self.assertNotIn("key", channel)



    def test_health_returns_json(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("time", response.json())

    def test_health_rejects_post(self):
        response = self.client.post("/api/health")
        self.assertEqual(response.status_code, 405)


class ForumPageTests(TestCase):
    def test_forum_page_is_public_and_seeds_csrf(self):
        response = self.client.get("/forum")

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("KFlow Community", body)
        self.assertIn('/forum.css', body)
        self.assertIn('/forum.js', body)
        self.assertIn("csrftoken", self.client.cookies)


class CSRFFlowTests(TestCase):
    def test_static_page_seeds_csrf_and_write_requires_matching_token(self):
        client = Client(enforce_csrf_checks=True)
        page = client.get("/login")
        self.assertEqual(page.status_code, 200)
        page_body = b"".join(page.streaming_content).decode("utf-8")
        self.assertIn("/csrf.js", page_body)
        self.assertIn("csrftoken", client.cookies)
        csrf = client.cookies["csrftoken"].value

        blocked = client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "admin123"}),
            content_type="application/json",
        )
        self.assertEqual(blocked.status_code, 403)

        allowed = client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "admin123"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(allowed.status_code, 200)


class MaintenanceCommandTests(TestCase):
    def test_cleanup_sessions_removes_expired_django_and_legacy_rows(self):
        from django.contrib.sessions.models import Session

        Session.objects.create(
            session_key="expired-django",
            session_data="e30=",
            expire_date=timezone.now() - timedelta(minutes=1),
        )
        LegacySession.objects.create(
            token="expired-legacy",
            role="user",
            username="expired",
            exp=timezone.now().timestamp() - 60,
            created_at="x",
            updated_at="x",
        )
        output = StringIO()
        call_command("cleanup_sessions", stdout=output)
        self.assertEqual(Session.objects.filter(session_key="expired-django").count(), 0)
        self.assertEqual(LegacySession.objects.filter(token="expired-legacy").count(), 0)
        self.assertIn("Removed", output.getvalue())

    def test_cleanup_upload_sessions_removes_expired_persistent_row(self):
        UploadSession.objects.create(
            upload_id="expired-upload",
            product_id=1,
            username="admin",
            level=3,
            original="archive.zip",
            size=1,
            count=1,
            platform="macOS",
            architecture="ARM64",
            expires_at=timezone.now().timestamp() - 60,
            created_at="x",
        )
        call_command("cleanup_upload_sessions", stdout=StringIO())
        self.assertFalse(UploadSession.objects.filter(upload_id="expired-upload").exists())
