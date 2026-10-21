from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.test import Client, TestCase, override_settings

from apps.catalog.models import Product, ProductPackage
from apps.downloads.models import UploadSession


class ProductUploadCSRFTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/login")
        response = self.client.post(
            "/api/admin/login",
            {"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.csrf = self.client.cookies["csrftoken"].value

        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = override_settings(BASE_DIR=self.root, MEDIA_ROOT=self.root / "uploads")
        override.enable()
        self.addCleanup(override.disable)
        self.product = Product.objects.create(
            name="CSRF upload", slug="csrf-upload", created_at="x", updated_at="x"
        )

    def test_direct_upload_requires_csrf_and_preserves_package(self):
        url = f"/api/admin/products/{self.product.pk}/upload"
        data = b"package\x00\xffbytes"
        headers = {
            "HTTP_X_FILENAME": "bundle.zip",
            "HTTP_X_PLATFORM": "Windows",
            "HTTP_X_ARCHITECTURE": "x64",
        }
        blocked = self.client.post(url, data, content_type="application/octet-stream", **headers)
        self.assertEqual(blocked.status_code, 403)
        self.assertFalse(ProductPackage.objects.filter(product=self.product).exists())

        allowed = self.client.post(
            url, data, content_type="application/octet-stream",
            HTTP_X_CSRFTOKEN=self.csrf, **headers,
        )
        self.assertEqual(allowed.status_code, 200, allowed.content)
        package = ProductPackage.objects.get(product=self.product)
        self.assertEqual((package.platform, package.architecture), ("Windows", "x64"))
        self.assertEqual((self.root / package.file_path).read_bytes(), data)

    def test_chunk_upload_requires_csrf_at_every_stage(self):
        data = b"chunk\x00\xffbytes"
        url = f"/api/admin/products/{self.product.pk}/upload-sessions"
        payload = {"filename": "bundle.zip", "size": len(data), "platform": "Windows", "architecture": "x64"}
        blocked = self.client.post(url, payload, content_type="application/json")
        self.assertEqual(blocked.status_code, 403)
        self.assertFalse(UploadSession.objects.exists())

        response = self.client.post(
            url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 200, response.content)
        upload_id = response.json()["upload_id"]
        chunk_url = f"/api/admin/upload-sessions/{upload_id}/chunks/0"
        self.assertEqual(
            self.client.post(chunk_url, data, content_type="application/octet-stream").status_code, 403,
        )
        response = self.client.post(
            chunk_url, data, content_type="application/octet-stream", HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 200, response.content)
        complete_url = f"/api/admin/upload-sessions/{upload_id}/complete"
        self.assertEqual(self.client.post(complete_url).status_code, 403)
        response = self.client.post(complete_url, HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(response.status_code, 200, response.content)
        package = ProductPackage.objects.get(product=self.product)
        self.assertEqual((self.root / package.file_path).read_bytes(), data)
        self.assertFalse(UploadSession.objects.exists())
