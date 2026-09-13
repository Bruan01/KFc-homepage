# pyright: reportMissingImports=false
"""Tests for the kflowstore creator shelf (user listings)."""
import json

from django.test import TestCase

from apps.accounts.models import User
from apps.points.models import PointAccount

from .models import ListingRedemption, StoreListing


def _make_user(username, balance=0):
    user = User.objects.create_user(username=username, password="pass1234", email=f"{username}@example.com")
    PointAccount.objects.create(user=user, balance=balance, updated_at="2026-01-01T00:00:00+00:00")
    return user


class ListingCreateTests(TestCase):
    def setUp(self):
        self.seller = _make_user("seller")
        self.client.login(username="seller", password="pass1234")

    def test_create_goes_to_pending(self):
        resp = self.client.post(
            "/api/store/listings/mine",
            json.dumps({
                "title": "Prompt 合集",
                "pricePoints": 50,
                "deliverableType": "text",
                "deliverableText": "感谢购买，这是说明。",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        listing = StoreListing.objects.get(title="Prompt 合集")
        self.assertEqual(listing.status, StoreListing.STATUS_PENDING)
        self.assertEqual(listing.seller_username, "seller")

    def test_rejects_low_price(self):
        resp = self.client.post(
            "/api/store/listings/mine",
            json.dumps({"title": "便宜货", "pricePoints": 5, "deliverableType": "text", "deliverableText": "x"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_code_type_requires_codes(self):
        resp = self.client.post(
            "/api/store/listings/mine",
            json.dumps({"title": "码商品", "pricePoints": 20, "deliverableType": "code", "stock": 5}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class ListingTradeTests(TestCase):
    def setUp(self):
        self.seller = _make_user("seller")
        self.buyer = _make_user("buyer", balance=100)
        self.listing = StoreListing.objects.create(
            seller_username="seller",
            title="教程包",
            price_points=30,
            stock=2,
            per_user_limit=1,
            deliverable_type=StoreListing.DELIVERABLE_TEXT,
            deliverable_text="这是教程链接：https://example.com",
            status=StoreListing.STATUS_ACTIVE,
        )
        self.client.login(username="buyer", password="pass1234")

    def _redeem(self):
        return self.client.post(
            f"/api/store/listings/{self.listing.pk}/redeem",
            json.dumps({"idempotencyKey": "test-key-12345678"}),
            content_type="application/json",
        )

    def test_purchase_transfers_points(self):
        resp = self._redeem()
        self.assertEqual(resp.status_code, 201)
        buyer_account = PointAccount.objects.get(user=self.buyer)
        seller = User.objects.get(username="seller")
        seller_account = PointAccount.objects.get(user=seller)
        self.assertEqual(buyer_account.balance, 70)
        self.assertEqual(seller_account.balance, 30)
        self.assertEqual(ListingRedemption.objects.count(), 1)
        self.assertEqual(resp.json()["redemption"]["payload"], "这是教程链接：https://example.com")

    def test_idempotent_purchase(self):
        self._redeem()
        resp = self._redeem()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["created"])
        buyer_account = PointAccount.objects.get(user=self.buyer)
        self.assertEqual(buyer_account.balance, 70)

    def test_cannot_buy_own_listing(self):
        self.client.logout()
        self.client.login(username="seller", password="pass1234")
        resp = self._redeem()
        self.assertEqual(resp.status_code, 403)

    def test_sold_out_shelves_listing(self):
        self.listing.stock = 1
        self.listing.save(update_fields=["stock"])
        self._redeem()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, StoreListing.STATUS_OFF_SHELF)

    def test_active_listings_public(self):
        resp = self.client.get("/api/store/listings")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["items"]), 1)
        # pending listings are hidden
        self.listing.status = StoreListing.STATUS_PENDING
        self.listing.save(update_fields=["status"])
        resp = self.client.get("/api/store/listings")
        self.assertEqual(resp.json()["items"], [])


class ListingReviewTests(TestCase):
    def setUp(self):
        self.seller = _make_user("seller")
        self.listing = StoreListing.objects.create(
            seller_username="seller",
            title="待审核",
            price_points=20,
            deliverable_type=StoreListing.DELIVERABLE_TEXT,
            deliverable_text="x",
            status=StoreListing.STATUS_PENDING,
        )
        self.admin = User.objects.create_user(username="root", password="pass1234", email="r@example.com")

    def test_review_flow(self):
        # settings.ADMIN_USERNAME defaults to "admin"; use that account to pass permission check
        admin = User.objects.create_user(username="admin", password="pass1234", email="ad@example.com")
        self.client.login(username="admin", password="pass1234")
        resp = self.client.post(
            f"/api/admin/store/listings/{self.listing.pk}/review",
            json.dumps({"approve": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, StoreListing.STATUS_ACTIVE)
