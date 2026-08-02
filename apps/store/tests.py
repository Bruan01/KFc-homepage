from django.conf import settings
from django.test import TestCase

from apps.accounts.models import User
from apps.points.models import PointAccount, PointLedger
from apps.points.services import apply_ledger, now_iso
from .crypto import decrypt_code
from .models import StoreCode, StoreProduct, StoreRedemption


class StorePageTests(TestCase):
    def test_store_loads_auth_before_rendering_products(self):
        response = self.client.get("/store")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        self.assertNotIn("Promise.all([loadProducts(), loadUser()]).catch(() => say('页面加载失败，请稍后重试。', 'error'))", body)
        self.assertIn("await loadUser(); await loadProducts();", body)
        self.assertIn("json('/api/user/me')", body)


class StoreAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            username="store-user",
            email="store@example.com",
            email_verified_at=now_iso(),
            created_at=now_iso(),
        )
        self.other = User.objects.create(
            username="store-other",
            email="other@example.com",
            email_verified_at=now_iso(),
            created_at=now_iso(),
        )
        apply_ledger(user=self.user, event_type="seed", points_delta=50, idempotency_key="seed:store-user")
        self.product = StoreProduct.objects.create(
            slug="music-code",
            name="音乐兑换码",
            summary="一枚测试兑换码",
            points_cost=20,
            per_user_limit=1,
            status=StoreProduct.ACTIVE,
            created_by="admin",
        )
        self.code = StoreCode.objects.create(
            product=self.product,
            code_ciphertext="",
            code_digest="placeholder",
            imported_by="admin",
        )
        from .crypto import encrypt_code, digest_code
        self.code.code_ciphertext = encrypt_code("MUSIC-ABC-123")
        self.code.code_digest = digest_code("MUSIC-ABC-123")
        self.code.save(update_fields=["code_ciphertext", "code_digest"])

    def test_public_products_hide_drafts_and_guest_cannot_redeem(self):
        StoreProduct.objects.create(slug="draft-code", name="Draft", status=StoreProduct.DRAFT)
        response = self.client.get("/api/store/products")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["slug"] for item in response.json()["items"]], ["music-code"])
        self.assertEqual(self.client.post("/api/store/redeem", {"productId": self.product.pk}, content_type="application/json").status_code, 401)

    def test_redeem_is_atomic_idempotent_and_returns_only_own_code(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/store/redeem",
            {"productId": self.product.pk, "idempotencyKey": "store-redeem-key-1"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["balance"], 30)
        self.assertEqual(response.json()["redemption"]["code"], "MUSIC-ABC-123")
        self.code.refresh_from_db()
        self.assertEqual(self.code.status, StoreCode.REDEEMED)
        self.assertEqual(PointLedger.objects.filter(event_type="store_redeem").count(), 1)

        duplicate = self.client.post(
            "/api/store/redeem",
            {"productId": self.product.pk, "idempotencyKey": "store-redeem-key-1"},
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()["created"])
        self.assertEqual(PointAccount.objects.get(user=self.user).balance, 30)
        self.assertEqual(StoreRedemption.objects.filter(user=self.user).count(), 1)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/store/redemptions").json()["items"], [])

    def test_insufficient_points_does_not_consume_code(self):
        self.client.force_login(self.other)
        response = self.client.post(
            "/api/store/redeem",
            {"productId": self.product.pk, "idempotencyKey": "store-poor-user-key"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.code.refresh_from_db()
        self.assertEqual(self.code.status, StoreCode.AVAILABLE)
        self.assertFalse(StoreRedemption.objects.exists())

    def test_admin_imports_codes_without_leaking_plaintext(self):
        self.client.post("/api/admin/login", {"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}, content_type="application/json")
        response = self.client.post(
            f"/api/admin/store/products/{self.product.pk}/codes",
            {"codes": "NEW-001\nNEW-002\nNEW-001"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["imported"], 2)
        listing = self.client.get(f"/api/admin/store/products/{self.product.pk}/codes")
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn("NEW-001", listing.content.decode())
        stored = StoreCode.objects.get(code_digest=__import__("apps.store.crypto", fromlist=["digest_code"]).digest_code("NEW-001"))
        self.assertNotEqual(stored.code_ciphertext, "NEW-001")
        self.assertEqual(decrypt_code(stored.code_ciphertext), "NEW-001")
