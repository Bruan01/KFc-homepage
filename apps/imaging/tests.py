import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.db import transaction
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.catalog.models import SystemSetting
from apps.points.models import PointAccount, PointLedger
from apps.points.services import apply_ledger, now_iso
from .models import ImageGenerationJob
from .config import get_provider_config
from .services import ImageProviderError, process_generation


class ImagingAPITests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media_root = Path(self.temp.name) / "uploads"
        self.media_root.mkdir()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        self.alice = User.objects.create(
            username="alice-imaging", email="alice-imaging@example.com",
            email_verified_at=now_iso(), created_at=now_iso(),
        )
        self.bob = User.objects.create(
            username="bob-imaging", email="bob-imaging@example.com",
            email_verified_at=now_iso(), created_at=now_iso(),
        )
        with transaction.atomic():
            apply_ledger(user=self.alice, event_type="seed", points_delta=50, idempotency_key="seed:alice-imaging")
            apply_ledger(user=self.bob, event_type="seed", points_delta=50, idempotency_key="seed:bob-imaging")
        self.enqueue = patch("apps.imaging.services.enqueue_generation").start()
        self.addCleanup(patch.stopall)

    def post_generation(self, client, **extra):
        payload = {"prompt": "一座漂浮在云海中的图书馆", "idempotencyKey": "imaging-key-001"}
        payload.update(extra)
        return client.post("/api/imaging/generations", payload, content_type="application/json")

    def test_requires_user_and_page_redirects_to_login(self):
        self.assertEqual(self.client.get("/imaging").status_code, 302)
        response = self.client.post("/api/imaging/generations", {"prompt": "x"}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_default_admin_without_user_row_can_open_imaging(self):
        self.client.logout()
        login = self.client.post(
            "/api/admin/login",
            {"username": "admin", "password": "admin123"},
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200, login.content)
        self.assertEqual(self.client.get("/imaging").status_code, 200)

    def test_creation_deducts_points_and_is_idempotent(self):
        self.client.force_login(self.alice)
        response = self.post_generation(self.client)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["balance"], 40)
        job = ImageGenerationJob.objects.get(pk=response.json()["id"])
        self.assertEqual(job.user_id, self.alice.pk)
        self.assertEqual(PointLedger.objects.filter(user=self.alice, event_type="image_generation").count(), 1)

        duplicate = self.post_generation(self.client)
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()["created"])
        self.assertEqual(duplicate.json()["id"], str(job.pk))
        self.assertEqual(PointLedger.objects.filter(user=self.alice, event_type="image_generation").count(), 1)

    @patch("apps.imaging.services.generate_image_bytes", return_value=b"image-bytes")
    def test_success_persists_file_hash_and_private_history(self, _generate):
        self.client.force_login(self.alice)
        response = self.post_generation(self.client)
        job = ImageGenerationJob.objects.get(pk=response.json()["id"])
        process_generation(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, ImageGenerationJob.COMPLETED)
        self.assertEqual(job.image_sha256, hashlib.sha256(b"image-bytes").hexdigest())
        self.assertTrue(job.image.storage.exists(job.image.name))
        history = self.client.get("/api/imaging/history")
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["id"] for item in history.json()], [str(job.pk)])

    @patch("apps.imaging.services.generate_image_bytes", side_effect=ImageProviderError("provider unavailable"))
    def test_failure_refunds_points_and_is_persisted(self, _generate):
        self.client.force_login(self.alice)
        response = self.post_generation(self.client, idempotencyKey="imaging-failure-key")
        process_generation(response.json()["id"])
        job = ImageGenerationJob.objects.get(pk=response.json()["id"])
        self.assertEqual(job.status, ImageGenerationJob.FAILED)
        self.assertEqual(job.error, "provider unavailable")
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 50)
        self.assertEqual(PointLedger.objects.filter(user=self.alice, event_type="image_generation_refund").count(), 1)

    def test_history_and_image_endpoint_are_isolated_by_user(self):
        job = ImageGenerationJob.objects.create(
            user=self.alice, prompt="alice", size="1024x1024", quality="low", output_format="png",
            status=ImageGenerationJob.COMPLETED, idempotency_key="alice-history-key",
        )
        job.image.save("alice.png", ContentFile(b"alice-image"), save=True)
        other = ImageGenerationJob.objects.create(
            user=self.bob, prompt="bob", size="1024x1024", quality="low", output_format="png",
            status=ImageGenerationJob.COMPLETED, idempotency_key="bob-history-key",
        )
        other.image.save("bob.png", ContentFile(b"bob-image"), save=True)

        self.client.force_login(self.alice)
        self.assertEqual([item["id"] for item in self.client.get("/api/imaging/history").json()], [str(job.pk)])
        self.assertEqual(self.client.get(f"/api/imaging/generations/{other.pk}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/imaging/generations/{other.pk}/image").status_code, 404)

    def test_download_is_attachment_and_isolated_by_user(self):
        job = ImageGenerationJob.objects.create(
            user=self.alice, prompt="alice download", size="1024x1024", quality="low", output_format="png",
            status=ImageGenerationJob.COMPLETED, idempotency_key="alice-download-key",
        )
        job.image.save("alice-download.png", ContentFile(b"download-bytes"), save=True)
        self.client.force_login(self.alice)
        response = self.client.get(f"/api/imaging/generations/{job.pk}/download")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"download-bytes")
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(f"/api/imaging/generations/{job.pk}/download").status_code, 404)

    def test_only_super_admin_can_read_and_update_provider_settings_without_leaking_key(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get("/api/admin/imaging/settings").status_code, 401)

        self.client.logout()
        login = self.client.post(
            "/api/admin/login",
            {"username": "admin", "password": "admin123"},
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200, login.content)
        response = self.client.post(
            "/api/admin/imaging/settings",
            {
                "baseUrl": "https://cpa.example.test/v1",
                "model": "gpt-image-enterprise",
                "timeoutSeconds": 420,
                "apiKey": "super-secret-key-1234",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()["item"]
        self.assertTrue(payload["apiKeyConfigured"])
        self.assertEqual(payload["apiKeyMasked"], "••••1234")
        self.assertNotIn("super-secret-key-1234", response.content.decode())
        self.assertEqual(get_provider_config()["api_key"], "super-secret-key-1234")
        self.assertEqual(get_provider_config()["model"], "gpt-image-enterprise")
        self.assertEqual(get_provider_config()["timeout_seconds"], 420)

        cleared = self.client.post(
            "/api/admin/imaging/settings",
            {"clearApiKey": True},
            content_type="application/json",
        )
        self.assertEqual(cleared.status_code, 200, cleared.content)
        self.assertFalse(cleared.json()["item"]["apiKeyConfigured"])
        self.assertEqual(SystemSetting.objects.get(pk="imaging.cpa.api_key").setting_value, "")
