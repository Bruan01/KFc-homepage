from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.downloads.models import Download, DownloadEntitlement
from .models import PointAccount, PointLedger
from .services import apply_ledger, now_iso


class PointsAPITests(TestCase):
    def setUp(self):
        self.user = User(username="points-user", email="points@example.com", email_verified_at=now_iso(), created_at=now_iso())
        self.user.set_password("password123")
        self.user.save()
        self.product = Product.objects.create(
            slug="paid-tool", name="Paid Tool", status="published", file_name="paid.zip",
            file_path="uploads/paid.zip", file_size=4, created_at=now_iso(), updated_at=now_iso(),
        )
        self.client.force_login(self.user)
        with __import__("django").db.transaction.atomic():
            apply_ledger(
                user=self.user, event_type="seed", points_delta=50,
                idempotency_key="seed:points-user", description="seed",
            )

    def test_redeem_download_is_idempotent_and_atomic(self):
        Download.objects.create(product=self.product, user=self.user, downloaded_at=now_iso())
        response = self.client.post("/api/points/redeem-download", {
            "productId": self.product.pk, "idempotencyKey": "redeem-key-001",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["created"])
        self.assertEqual(response.json()["balance"], 40)
        response2 = self.client.post("/api/points/redeem-download", {
            "productId": self.product.pk, "idempotencyKey": "redeem-key-001",
        }, content_type="application/json")
        self.assertEqual(response2.status_code, 200)
        self.assertFalse(response2.json()["created"])
        self.assertEqual(DownloadEntitlement.objects.filter(user=self.user).count(), 1)
        self.assertEqual(PointLedger.objects.filter(event_type="download_redemption").count(), 1)

    def test_free_download_must_be_used_before_redemption(self):
        response = self.client.post("/api/points/redeem-download", {
            "productId": self.product.pk, "idempotencyKey": "redeem-key-002",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 409)

    def test_admin_can_adjust_freeze_and_update_rules(self):
        self.client.logout()
        self.client.post("/api/admin/login", {
            "username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD,
        }, content_type="application/json")
        response = self.client.post("/api/admin/points/adjust", {
            "userId": self.user.pk, "pointsDelta": 5, "contributionDelta": 2, "reason": "manual",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["account"]["balance"], 55)
        response = self.client.post("/api/admin/points/freeze", {"userId": self.user.pk}, content_type="application/json")
        self.assertEqual(response.json()["status"], "frozen")
        response = self.client.post("/api/admin/points/settings", {"download_default_cost": 17}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item"]["download_default_cost"], 17)

    def test_wallet_ledger_and_entitlement_views(self):
        response = self.client.get("/api/points/me")
        self.assertEqual(response.status_code, 200)
        self.assertIn("balance", response.json())
        response = self.client.get("/api/points/ledger", {"page": 1, "pageSize": 10})
        self.assertGreaterEqual(response.json()["total"], 1)
        response = self.client.get("/api/points/download-entitlements")
        self.assertEqual(response.status_code, 200)
