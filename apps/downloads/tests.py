import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.catalog.models import Product, ProductPackage
from apps.points.services import now_iso
from .models import Download, DownloadRequest, UploadSession


class DownloadAPITests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "uploads").mkdir()
        (self.root / "uploads" / "tool.zip").write_bytes(b"0123456789")
        self.override = override_settings(BASE_DIR=self.root, MEDIA_ROOT=self.root / "uploads")
        self.override.enable(); self.addCleanup(self.override.disable)
        self.user = User(username="download-user", email="download@example.com", email_verified_at=now_iso(), created_at=now_iso())
        self.user.set_password("password123"); self.user.save()
        self.product = Product.objects.create(
            slug="tool", name="Tool", version="1.0", status="published", file_name="tool.zip",
            file_path="uploads/tool.zip", file_size=10, file_sha256="", created_at=now_iso(), updated_at=now_iso(),
        )
        self.client.force_login(self.user)

    def body(self, response):
        return b"".join(response.streaming_content) if getattr(response, "streaming", False) else response.content

    def test_first_download_streams_and_second_requires_quota(self):
        response = self.client.get("/download/tool")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response), b"0123456789")
        self.assertEqual(Download.objects.filter(user=self.user, product=self.product).count(), 1)
        response = self.client.get("/download/tool")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "download quota used")

    def test_range_download_returns_206_without_double_count(self):
        response = self.client.get("/download/tool")
        self.body(response)
        response = self.client.get("/download/tool", HTTP_RANGE="bytes=2-5")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 2-5/10")
        self.assertEqual(self.body(response), b"2345")
        self.assertEqual(Download.objects.filter(user=self.user).count(), 1)
        response = self.client.get("/download/tool", HTTP_RANGE="bytes=99-100")
        self.assertEqual(response.status_code, 416)

    def test_approved_request_allows_second_download_and_is_consumed(self):
        Download.objects.create(product=self.product, user=self.user, downloaded_at=now_iso())
        request_row = DownloadRequest.objects.create(user=self.user, product=self.product, status="approved", created_at=now_iso())
        response = self.client.get("/download/tool")
        self.assertEqual(response.status_code, 200)
        self.body(response)
        request_row.refresh_from_db()
        self.assertIsNotNone(request_row.consumed_at)

    def test_request_history_quota_and_admin_review(self):
        Download.objects.create(product=self.product, user=self.user, downloaded_at=now_iso())
        response = self.client.post("/api/products/tool/request-download", {"reason": "need again"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        row = DownloadRequest.objects.get(user=self.user)
        self.assertEqual(self.client.get("/api/user/requests").json()["items"][0]["id"], row.pk)
        self.assertTrue(self.client.get("/api/user/download-quota").json()["items"][0]["has_pending_request"])
        self.client.logout()
        self.client.post("/api/admin/login", {"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}, content_type="application/json")
        response = self.client.get("/api/admin/download-requests")
        self.assertEqual(len(response.json()["items"]), 1)
        response = self.client.post(f"/api/admin/download-requests/{row.pk}/approve", {"note": "ok"}, content_type="application/json")
        self.assertEqual(response.json()["status"], "approved")


class ChunkUploadTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / "uploads").mkdir()
        self.override = override_settings(BASE_DIR=self.root, MEDIA_ROOT=self.root / "uploads")
        self.override.enable(); self.addCleanup(self.override.disable)
        self.product = Product.objects.create(slug="upload", name="Upload", status="draft", created_at=now_iso(), updated_at=now_iso())
        self.client.post("/api/admin/login", {"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}, content_type="application/json")

    def test_chunk_session_survives_database_roundtrip_and_completes(self):
        data = b"chunk-data"
        sha = hashlib.sha256(data).hexdigest()
        response = self.client.post(f"/api/admin/products/{self.product.pk}/upload-sessions", {
            "filename": "code.zip", "size": len(data), "platform": "macOS", "architecture": "ARM64", "sha256": sha,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        upload_id = response.json()["upload_id"]
        self.assertTrue(UploadSession.objects.filter(upload_id=upload_id).exists())
        response = self.client.post(f"/api/admin/upload-sessions/{upload_id}/chunks/0", data=data, content_type="application/octet-stream")
        self.assertEqual(response.status_code, 200, response.content)
        response = self.client.post(f"/api/admin/upload-sessions/{upload_id}/complete", {}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.product.refresh_from_db()
        self.assertTrue(self.product.file_path)
        self.assertEqual(ProductPackage.objects.filter(product=self.product).count(), 1)
        self.assertFalse(UploadSession.objects.filter(upload_id=upload_id).exists())
