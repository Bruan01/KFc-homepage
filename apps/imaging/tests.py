# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportArgumentType=false, reportCallIssue=false
import base64
import json
import hashlib
import io
import urllib.error
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.core.files.base import ContentFile
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.catalog.models import SystemSetting
from apps.points.models import PointAccount, PointLedger
from apps.points.services import apply_ledger, now_iso
from .models import ImageGenerationJob, ImagingProvider, ImagingProviderAttempt
from .config import get_provider_config, provider_payload
from .providers.openai import ImageProviderError as OpenAIProviderError
from .providers.openai import OpenAIImagesClient, normalize_openai_api_base_url
from .services import (
    ImageProviderError,
    _cache_key,
    _compressed_image,
    generate_image_bytes,
    process_generation,
    recover_stale_jobs,
    select_provider_candidates,
    test_provider_connection,
)


def image_bytes(image_format="PNG", size=(64, 64), quality=100):
    output = io.BytesIO()
    Image.new("RGB", size, (36, 92, 180)).save(output, format=image_format, quality=quality)
    return output.getvalue()


class ProviderResponseStub:
    def __init__(self, payload, *, status=200, headers=None):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, amount=-1):
        return self.payload if amount < 0 else self.payload[:amount]


class OpenAIImagesClientTests(TestCase):
    @patch("apps.imaging.providers.openai.urllib.request.urlopen")
    def test_generate_uses_v1_images_endpoint_and_openai_payload(self, urlopen):
        encoded = base64.b64encode(b"generated-image").decode("ascii")
        urlopen.return_value = ProviderResponseStub({"data": [{"b64_json": encoded}]})
        client = OpenAIImagesClient("https://hub.example.test", "secret", 120)

        content = client.generate(
            model="gpt-image-2",
            prompt="一只橙色的猫",
            size="1024x1024",
            quality="medium",
            output_format="png",
        )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://hub.example.test/v1/images/generations")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data),
            {
                "model": "gpt-image-2",
                "prompt": "一只橙色的猫",
                "size": "1024x1024",
                "quality": "medium",
                "output_format": "png",
                "n": 1,
            },
        )
        self.assertEqual(content, b"generated-image")

    @patch("apps.imaging.providers.openai.urllib.request.urlopen")
    def test_http_error_preserves_safe_diagnostic_metadata(self, urlopen):
        body = json.dumps(
            {"error": {"message": "model is unavailable", "type": "invalid_request_error", "code": "model_not_found"}}
        ).encode("utf-8")
        urlopen.side_effect = urllib.error.HTTPError(
            "https://hub.example.test/v1/images/generations",
            404,
            "Not Found",
            {"x-request-id": "req_safe_123"},
            io.BytesIO(body),
        )
        client = OpenAIImagesClient("https://hub.example.test", "secret", 120)

        with self.assertRaises(OpenAIProviderError) as captured:
            client.generate(
                model="gpt-image-2",
                prompt="test",
                size="1024x1024",
                quality="low",
                output_format="png",
            )

        error = captured.exception
        self.assertEqual(error.category, "model_not_available")
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.error_code, "model_not_found")
        self.assertEqual(error.request_id, "req_safe_123")
        self.assertFalse(error.retryable)

    def test_base_url_rejects_credentials_query_and_fragment(self):
        invalid_urls = (
            "https://user:pass@hub.example.test/v1",
            "https://hub.example.test/v1?token=secret",
            "https://hub.example.test/v1#images",
        )
        for value in invalid_urls:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_openai_api_base_url(value)


class ImagingAPITests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media_root = Path(self.temp.name) / "uploads"
        self.media_root.mkdir()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root, IMAGING_ORIGINAL_ROOT=Path(self.temp.name) / "originals")
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
        self.provider = ImagingProvider.objects.create(
            name="测试显影服务",
            base_url="https://imaging.example.test/v1",
            api_key="test-provider-key",
            model="gpt-image-2",
        )
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

    def test_creation_returns_json_when_points_are_insufficient(self):
        PointAccount.objects.filter(user=self.alice).update(balance=0)
        self.client.force_login(self.alice)

        response = self.post_generation(self.client, idempotencyKey="imaging-insufficient-points")

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["error"], "积分不足，请先获取足够积分后再生成。")
        self.assertFalse(ImageGenerationJob.objects.filter(user=self.alice).exists())

    @patch("apps.imaging.services._request_provider_image")
    def test_success_persists_file_hash_and_private_history(self, generate):
        raw = image_bytes()
        generate.return_value = raw
        self.client.force_login(self.alice)
        response = self.post_generation(self.client)
        job = ImageGenerationJob.objects.get(pk=response.json()["id"])
        process_generation(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, ImageGenerationJob.COMPLETED)
        stored = job.image.read()
        self.assertEqual(job.image_sha256, hashlib.sha256(stored).hexdigest())
        with job.original_image.open("rb") as original:
            self.assertEqual(original.read(), raw)
        self.assertNotIn(str(self.media_root), job.original_image.path)
        self.assertEqual(job.original_bytes, len(raw))
        self.assertEqual(job.stored_bytes, len(stored))
        self.assertLessEqual(job.stored_bytes, job.original_bytes)
        self.assertTrue(job.image.storage.exists(job.image.name))
        history = self.client.get("/api/imaging/history")
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["id"] for item in history.json()], [str(job.pk)])

    @patch("apps.imaging.services._request_provider_image", side_effect=ImageProviderError("provider unavailable"))
    def test_failure_refunds_points_and_is_persisted(self, _generate):
        self.client.force_login(self.alice)
        response = self.post_generation(self.client, idempotencyKey="imaging-failure-key")
        process_generation(response.json()["id"])
        job = ImageGenerationJob.objects.get(pk=response.json()["id"])
        self.assertEqual(job.status, ImageGenerationJob.FAILED)
        self.assertEqual(job.error, "provider unavailable")
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 50)
        self.assertEqual(PointLedger.objects.filter(user=self.alice, event_type="image_generation_refund").count(), 1)

    def test_interrupted_generation_is_requeued_without_losing_points(self):
        self.client.force_login(self.alice)
        response = self.post_generation(self.client, idempotencyKey="interrupted-generation-key")
        job = ImageGenerationJob.objects.get(pk=response.json()["id"])
        job.status = ImageGenerationJob.GENERATING
        job.started_at = timezone.now() - timedelta(hours=1)
        job.save(update_fields=["status", "started_at", "updated_at"])

        with override_settings(IMAGING_JOB_STALE_SECONDS=60):
            self.assertEqual(recover_stale_jobs(), 1)

        job.refresh_from_db()
        self.assertEqual(job.status, ImageGenerationJob.QUEUED)
        self.assertIsNone(job.started_at)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 40)
        self.assertEqual(PointLedger.objects.filter(user=self.alice, event_type="image_generation_refund").count(), 0)

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

    def test_cache_hit_creates_completed_job_and_still_deducts_full_points(self):
        prompt = "一座漂浮在云海中的图书馆"
        source = ImageGenerationJob.objects.create(
            user=self.alice, prompt=prompt, size="1024x1024", quality="low", output_format="png",
            status=ImageGenerationJob.COMPLETED, idempotency_key="source-cache-key",
            cache_key=_cache_key(self.alice.pk, prompt, "1024x1024", "low", "png"), completed_at=timezone.now(),
            image_sha256="a" * 64, original_bytes=1000, stored_bytes=700,
        )
        source.image.save("cache-source.png", ContentFile(image_bytes()), save=True)
        source.original_image.save("original.png", ContentFile(image_bytes()), save=True)
        self.client.force_login(self.alice)

        response = self.post_generation(self.client, idempotencyKey="cache-hit-key-002")

        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(response.json()["cache_hit"])
        self.assertEqual(response.json()["cache_source_id"], str(source.pk))
        cached = ImageGenerationJob.objects.get(pk=response.json()["id"])
        self.assertEqual(cached.status, ImageGenerationJob.COMPLETED)
        self.assertEqual(cached.image.name, source.image.name)
        self.assertEqual(cached.original_image.name, source.original_image.name)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 40)
        self.enqueue.assert_not_called()

    def test_cache_is_private_expires_and_requires_existing_file(self):
        prompt = "一座漂浮在云海中的图书馆"
        alice_key = _cache_key(self.alice.pk, prompt, "1024x1024", "low", "png")
        bob_key = _cache_key(self.bob.pk, prompt, "1024x1024", "low", "png")
        expired = ImageGenerationJob.objects.create(
            user=self.alice, prompt=prompt, size="1024x1024", quality="low", output_format="png",
            status=ImageGenerationJob.COMPLETED, idempotency_key="expired-cache-key", cache_key=alice_key,
            completed_at=timezone.now() - timedelta(days=31), image="missing-expired.png",
        )
        ImageGenerationJob.objects.filter(pk=expired.pk).update(completed_at=timezone.now() - timedelta(days=31))
        ImageGenerationJob.objects.create(
            user=self.bob, prompt=prompt, size="1024x1024", quality="low", output_format="png",
            status=ImageGenerationJob.COMPLETED, idempotency_key="other-user-cache-key", cache_key=bob_key,
            completed_at=timezone.now(), image="other-user.png",
        )
        self.client.force_login(self.alice)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_generation(self.client, idempotencyKey="cache-miss-key-003")

        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["cache_hit"])
        self.enqueue.assert_called_once()

    def test_image_endpoint_supports_private_conditional_cache(self):
        content = image_bytes()
        job = ImageGenerationJob.objects.create(
            user=self.alice, prompt="etag", size="1024x1024", quality="low", output_format="png",
            status=ImageGenerationJob.COMPLETED, idempotency_key="etag-image-key",
            image_sha256=hashlib.sha256(content).hexdigest(), completed_at=timezone.now(),
        )
        job.image.save("etag.png", ContentFile(content), save=True)
        self.client.force_login(self.alice)
        url = f"/api/imaging/generations/{job.pk}/image"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, max-age=86400")
        self.assertEqual(response["ETag"], f'"{job.image_sha256}"')
        self.assertIn("Last-Modified", response)
        conditional = self.client.get(url, HTTP_IF_NONE_MATCH=response["ETag"])
        self.assertEqual(conditional.status_code, 304)

    def test_compression_preserves_requested_format_and_dimensions(self):
        for output_format, pillow_format in (("png", "PNG"), ("jpeg", "JPEG"), ("webp", "WEBP")):
            raw = image_bytes(pillow_format, size=(80, 48), quality=100)
            stored = _compressed_image(raw, output_format)
            self.assertLessEqual(len(stored), len(raw))
            with Image.open(io.BytesIO(stored)) as result:
                self.assertEqual(result.size, (80, 48))
                self.assertEqual(result.format, pillow_format)

    def test_invalid_provider_image_is_rejected_and_refunded(self):
        self.client.force_login(self.alice)
        response = self.post_generation(self.client, idempotencyKey="invalid-image-key")
        with patch("apps.imaging.services._request_provider_image", return_value=b"not-an-image"):
            process_generation(response.json()["id"])
        job = ImageGenerationJob.objects.get(pk=response.json()["id"])
        self.assertEqual(job.status, ImageGenerationJob.FAILED)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 50)

    def create_original_job(self):
        """Create distinct preview/original files for download assertions."""
        job = ImageGenerationJob.objects.create(
            user=self.alice, prompt="alice download", size="1024x1024", quality="low", output_format="png",
            status=ImageGenerationJob.COMPLETED, idempotency_key=str(uuid4()),
        )
        job.image.save("preview.png", ContentFile(b"preview-bytes"), save=True)
        job.original_image.save("original.png", ContentFile(b"original-provider-bytes"), save=True)
        self.client.force_login(self.alice)
        return job

    def download_original(self, job, request_key=None, **extra):
        """Submit an explicit confirmation using a unique key per download."""
        return self.client.post(f"/api/imaging/generations/{job.pk}/download",
            {"confirmed": True, "idempotency_key": request_key or str(uuid4()), **extra}, content_type="application/json")

    def test_original_download_charges_each_confirmation_and_serves_original(self):
        job = self.create_original_job()
        for balance in (49, 48):
            response = self.download_original(job)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.content, b"original-provider-bytes")
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(int(response["X-Points-Balance"]), balance)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 48)
        self.assertEqual(PointLedger.objects.filter(event_type="image_download", user=self.alice).count(), 2)

    def test_original_download_retry_does_not_double_charge(self):
        job = self.create_original_job()
        request_key = str(uuid4())
        for _ in range(2):
            self.assertEqual(self.download_original(job, request_key).status_code, 200)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 49)
        other_job = self.create_original_job()
        self.assertEqual(self.download_original(other_job, request_key).status_code, 409)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 49)

    def test_download_needs_confirmation_and_rejects_get(self):
        job = self.create_original_job()
        self.assertEqual(self.client.get(f"/api/imaging/generations/{job.pk}/download").status_code, 405)
        self.assertEqual(self.download_original(job, confirmed=False).status_code, 400)
        self.assertEqual(self.download_original(job, "invalid-key").status_code, 400)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 50)

    def test_original_download_is_private_and_requires_login(self):
        job = self.create_original_job()
        with self.assertRaises(ValueError):
            _ = job.original_image.url
        self.client.force_login(self.bob)
        self.assertEqual(self.download_original(job).status_code, 404)
        self.client.logout()
        self.assertEqual(self.download_original(job).status_code, 401)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 50)

    def test_original_download_insufficient_and_frozen_accounts(self):
        job = self.create_original_job()
        PointAccount.objects.filter(user=self.alice).update(balance=0)
        self.assertEqual(self.download_original(job).status_code, 409)
        PointAccount.objects.filter(user=self.alice).update(balance=50, status="frozen")
        self.assertEqual(self.download_original(job).status_code, 403)
        self.assertFalse(PointLedger.objects.filter(event_type="image_download").exists())

    def test_original_download_allows_exactly_one_point(self):
        job = self.create_original_job()
        PointAccount.objects.filter(user=self.alice).update(balance=1)
        self.assertEqual(self.download_original(job).status_code, 200)
        self.assertEqual(self.download_original(job).status_code, 409)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 0)

    def test_missing_original_never_charges_or_falls_back_to_preview(self):
        job = self.create_original_job()
        job.original_image.storage.delete(job.original_image.name)
        self.assertEqual(self.download_original(job).status_code, 404)
        job.original_image = ""
        job.save(update_fields=["original_image"])
        self.assertEqual(self.download_original(job).status_code, 404)
        payload = self.client.get(f"/api/imaging/generations/{job.pk}").json()
        self.assertFalse(payload["original_available"])
        self.assertIsNone(payload["download_url"])
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 50)

    def test_paid_download_rolls_back_when_ledger_fails(self):
        job = self.create_original_job()
        with patch("apps.points.services.PointLedger.objects.create", side_effect=RuntimeError("ledger unavailable")):
            with self.assertRaises(RuntimeError):
                self.download_original(job)
        self.assertEqual(PointAccount.objects.get(user=self.alice).balance, 50)

    def test_legacy_cache_without_original_is_not_reused(self):
        job = self.create_original_job()
        job.original_image = ""
        job.cache_key = _cache_key(self.alice.pk, job.prompt, job.size, job.quality, job.output_format)
        job.completed_at = timezone.now()
        job.save()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_generation(self.client, prompt=job.prompt)
        self.assertFalse(response.json()["cache_hit"])
        self.enqueue.assert_called_once()

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
        self.assertEqual(get_provider_config()["base_url"], "https://cpa.example.test/v1")
        self.assertEqual(get_provider_config()["api_key"], "super-secret-key-1234")
        self.assertEqual(get_provider_config()["model"], "gpt-image-enterprise")
        self.assertEqual(get_provider_config()["timeout_seconds"], 420)

        job = ImageGenerationJob.objects.create(
            user=self.alice,
            prompt="测试新地址连接失败时的提示",
            size="1024x1024",
            quality="low",
            output_format="png",
            idempotency_key="saved-provider-url-used-for-generation",
        )
        with patch(
            "apps.imaging.providers.openai.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ) as urlopen:
            with self.assertRaisesRegex(ImageProviderError, "无法连接显影服务"):
                generate_image_bytes(job)
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://cpa.example.test/v1/images/generations",
        )

        cleared = self.client.post(
            "/api/admin/imaging/settings",
            {"clearApiKey": True},
            content_type="application/json",
        )
        self.assertEqual(cleared.status_code, 200, cleared.content)
        self.assertFalse(cleared.json()["item"]["apiKeyConfigured"])
        self.assertEqual(SystemSetting.objects.get(pk="imaging.cpa.api_key").setting_value, "")


class ImagingProviderPoolTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="pool-alice", password="secret-123")
        self.first = ImagingProvider.objects.create(
            name="主服务", base_url="https://primary.example.test/v1", api_key="primary-secret", model="gpt-image-2", weight=5, priority=100,
        )
        self.second = ImagingProvider.objects.create(
            name="备用服务", base_url="https://backup.example.test/v1", api_key="backup-secret", model="gpt-image-2", weight=3, priority=100,
        )
        self.third = ImagingProvider.objects.create(
            name="低权重服务", base_url="https://third.example.test/v1", api_key="third-secret", model="gpt-image-2", weight=1, priority=100,
        )

    def _job(self, key="provider-pool-job"):
        return ImageGenerationJob.objects.create(
            user=self.alice, prompt="测试服务轮换", size="1024x1024", quality="low", output_format="png", idempotency_key=key,
        )

    def test_smooth_weighted_round_robin_follows_weight_ratio(self):
        picks = [select_provider_candidates()[0] for _ in range(90)]
        self.assertEqual(picks.count(self.first.pk), 50)
        self.assertEqual(picks.count(self.second.pk), 30)
        self.assertEqual(picks.count(self.third.pk), 10)

    def test_bare_provider_origin_is_normalized_to_openai_v1(self):
        self.assertEqual(
            normalize_openai_api_base_url("https://hub.example.test"),
            "https://hub.example.test/v1",
        )
        self.assertEqual(
            normalize_openai_api_base_url("https://gateway.example.test/openai/v1/"),
            "https://gateway.example.test/openai/v1",
        )

    def test_provider_payload_exposes_effective_endpoints(self):
        completed = self._job("provider-count-completed")
        completed.provider = self.first
        completed.status = ImageGenerationJob.COMPLETED
        completed.save(update_fields=["provider", "status", "updated_at"])
        failed = self._job("provider-count-failed")
        failed.provider = self.first
        failed.status = ImageGenerationJob.FAILED
        failed.save(update_fields=["provider", "status", "updated_at"])

        self.first.base_url = "https://gateway.example.test"
        self.first.save(update_fields=["base_url"])

        payload = provider_payload(self.first)
        self.assertEqual(payload["successfulGenerationCount"], 1)

        self.assertEqual(payload["baseUrl"], "https://gateway.example.test/v1")
        self.assertEqual(payload["modelsEndpoint"], "https://gateway.example.test/v1/models")
        self.assertEqual(payload["imageGenerationEndpoint"], "https://gateway.example.test/v1/images/generations")

    @patch("apps.imaging.providers.openai.urllib.request.urlopen")
    def test_read_only_connection_check_verifies_configured_model(self, urlopen):
        urlopen.return_value = ProviderResponseStub({"data": [{"id": "gpt-image-2"}, {"id": "gpt-5"}]})

        result = test_provider_connection(self.first)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://primary.example.test/v1/models")
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(result["ok"])
        self.assertTrue(result["modelAvailable"])
        self.assertFalse(result["billable"])
        self.first.refresh_from_db()
        self.assertEqual(self.first.consecutive_failures, 0)
        self.assertIsNone(self.first.last_success_at)

    @patch("apps.imaging.providers.openai.urllib.request.urlopen")
    def test_connection_check_reports_model_not_available_without_changing_health(self, urlopen):
        urlopen.return_value = ProviderResponseStub({"data": [{"id": "gpt-image-1"}]})
        self.first.consecutive_failures = 2
        self.first.save(update_fields=["consecutive_failures"])

        result = test_provider_connection(self.first)

        self.assertFalse(result["ok"])
        self.assertFalse(result["modelAvailable"])
        self.assertEqual(result["errorCategory"], "model_not_available")
        self.first.refresh_from_db()
        self.assertEqual(self.first.consecutive_failures, 2)
        self.assertIsNone(self.first.circuit_open_until)

    def test_expired_circuit_is_selected_for_recovery_probe(self):
        self.second.enabled = False
        self.third.enabled = False
        self.second.save(update_fields=["enabled"])
        self.third.save(update_fields=["enabled"])
        self.first.consecutive_failures = 3
        self.first.circuit_open_until = timezone.now() - timedelta(seconds=1)
        self.first.save(update_fields=["consecutive_failures", "circuit_open_until"])

        self.assertEqual(select_provider_candidates(), [self.first.pk])

    @patch("apps.imaging.services._request_provider_image")
    def test_failed_provider_immediately_fails_over_and_records_attempts(self, request_image):
        job = self._job()
        request_image.side_effect = [ImageProviderError("primary offline"), b"image-from-backup"]

        content, selected = generate_image_bytes(job)

        self.assertEqual(content, b"image-from-backup")
        self.assertEqual(selected.pk, self.second.pk)
        attempts = list(job.provider_attempts.order_by("attempt_number"))
        self.assertEqual([(item.provider_id, item.status) for item in attempts], [
            (self.first.pk, ImagingProviderAttempt.FAILED),
            (self.second.pk, ImagingProviderAttempt.SUCCEEDED),
        ])
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.consecutive_failures, 1)
        self.assertEqual(self.second.consecutive_failures, 0)

    @patch("apps.imaging.services._request_provider_image", side_effect=ImageProviderError("offline"))
    def test_three_failures_open_circuit_and_skip_provider(self, _request_image):
        self.second.enabled = False
        self.third.enabled = False
        self.second.save(update_fields=["enabled"])
        self.third.save(update_fields=["enabled"])
        for index in range(3):
            with self.assertRaises(ImageProviderError):
                generate_image_bytes(self._job(f"circuit-job-{index}"))
        self.first.refresh_from_db()
        self.assertEqual(self.first.consecutive_failures, 3)
        self.assertIsNotNone(self.first.circuit_open_until)
        self.assertEqual(select_provider_candidates(), [])

    def test_provider_api_masks_key_and_allows_create_update_and_recover(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get("/api/admin/imaging/providers").status_code, 401)
        self.client.logout()
        login = self.client.post("/api/admin/login", {"username": "admin", "password": "admin123"}, content_type="application/json")
        self.assertEqual(login.status_code, 200, login.content)
        create = self.client.post(
            "/api/admin/imaging/providers/create",
            {"name":"新节点", "baseUrl":"https://new.example.test/v1", "apiKey":"new-top-secret-9988", "model":"gpt-image-new", "timeoutSeconds":420, "weight":2, "priority":50, "enabled":True},
            content_type="application/json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        item = create.json()["item"]
        self.assertEqual(item["apiKeyMasked"], "••••9988")
        self.assertNotIn("new-top-secret-9988", create.content.decode())
        provider_id = item["id"]
        toggle = self.client.generic("PATCH", f"/api/admin/imaging/providers/{provider_id}", json.dumps({"enabled":False}), content_type="application/json")
        self.assertEqual(toggle.status_code, 200, toggle.content)
        self.assertFalse(toggle.json()["item"]["enabled"])
        provider = ImagingProvider.objects.get(pk=provider_id)
        provider.consecutive_failures = 3
        provider.circuit_open_until = timezone.now() + timedelta(minutes=5)
        provider.save(update_fields=["consecutive_failures", "circuit_open_until"])
        recover = self.client.post(f"/api/admin/imaging/providers/{provider_id}/recover")
        self.assertEqual(recover.status_code, 200, recover.content)
        self.assertEqual(recover.json()["item"]["consecutiveFailures"], 0)
        self.assertIsNone(recover.json()["item"]["circuitOpenUntil"])

    @patch("apps.imaging.providers.openai.urllib.request.urlopen")
    def test_provider_configuration_check_api_is_read_only(self, urlopen):
        urlopen.return_value = ProviderResponseStub({"data": [{"id": "gpt-image-2"}]})
        login = self.client.post(
            "/api/admin/login",
            {"username": "admin", "password": "admin123"},
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200, login.content)

        response = self.client.post(f"/api/admin/imaging/providers/{self.first.pk}/test")

        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["result"]
        self.assertTrue(result["ok"])
        self.assertFalse(result["billable"])
        self.assertEqual(result["model"], "gpt-image-2")
        self.assertEqual(urlopen.call_args.args[0].get_method(), "GET")
