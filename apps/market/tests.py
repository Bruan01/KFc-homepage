from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.points.models import PointAccount, PointLedger
from apps.points.services import apply_ledger, now_iso

from .models import (
    MarketAsset,
    MarketBotDailyUsage,
    MarketBotInventory,
    MarketOrder,
    MarketPosition,
    MarketRound,
    MarketTreasuryLedger,
)
from .services import place_order, settle_round


class MarketPageTests(TestCase):
    def test_market_page_uses_user_auth_contract_for_private_market_data(self):
        response = self.client.get("/market")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        self.assertIn("json('/api/user/me')", body)
        self.assertNotIn("json('/api/account/me')", body)
        self.assertNotIn(
            "Promise.all([json('/api/points/me'), json('/api/market/portfolio'), json('/api/market/orders')])",
            body,
        )
        self.assertIn("卖出全部", body)
        self.assertIn("function submitOrder(assetId, side, button, quantityOverride = null)", body)
        self.assertIn("Number(button.dataset.quantity)", body)


class MarketServiceTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.user = User.objects.create(username="market-user", email="market@example.com", email_verified_at=now_iso(), created_at=now_iso())
        self.user.set_password("password123")
        self.user.save(update_fields=["password"])
        self.other = User.objects.create(username="market-other", email="other-market@example.com", email_verified_at=now_iso(), created_at=now_iso())
        apply_ledger(user=self.user, event_type="seed", points_delta=500, idempotency_key="market-seed-user")
        apply_ledger(user=self.other, event_type="seed", points_delta=500, idempotency_key="market-seed-other")
        self.round = MarketRound.objects.create(
            name="测试轮次",
            status=MarketRound.OPEN,
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(days=1),
            seed=42,
            fee_bps=0,
            spread_bps=0,
            max_order_points=500,
            daily_user_stake_limit=500,
            daily_user_orders_limit=5,
            daily_user_payout_limit=500,
            max_position_shares=10,
            max_profit_bps=1000,
            bot_initial_cash=1000,
            bot_cash_balance=1000,
            bot_max_loss=1000,
            bot_daily_payout_limit=1000,
        )
        self.asset = MarketAsset.objects.create(code="KTEST", name="K 测试股", base_price="10.00")
        self.inventory = MarketBotInventory.objects.create(round=self.round, asset=self.asset, initial_shares=20, shares_available=20)

    def _order(self, user=None, *, side="buy", quantity=2, key="market-order-key-1"):
        return place_order(user=user or self.user, asset_id=self.asset.pk, side=side, quantity=quantity, idempotency_key=key)

    def test_buy_sell_are_atomic_and_keep_points_and_bot_audit_consistent(self):
        before = PointAccount.objects.get(user=self.user).balance
        buy, balance, created = self._order()
        self.assertTrue(created)
        self.assertEqual(buy.source, MarketOrder.USER)
        self.assertEqual(balance["balance"], before - buy.gross_points)
        self.assertEqual(PointLedger.objects.filter(user=self.user, event_type="market_buy").count(), 1)
        self.inventory.refresh_from_db()
        self.round.refresh_from_db()
        position = MarketPosition.objects.get(user=self.user, round=self.round, asset=self.asset)
        self.assertEqual(self.inventory.shares_available, 18)
        self.assertEqual(self.round.reserved_payout_points, position.reserved_payout_points)
        self.assertEqual(self.round.bot_cash_balance, self.round.bot_initial_cash + buy.gross_points)

        sell, balance, created = self._order(side="sell", quantity=1, key="market-order-key-2")
        self.assertTrue(created)
        self.assertEqual(sell.source, MarketOrder.USER)
        self.assertEqual(balance["balance"], before - buy.gross_points + sell.net_points)
        self.assertEqual(PointLedger.objects.filter(user=self.user, event_type__in=["market_buy", "market_sell"]).count(), 2)
        self.inventory.refresh_from_db()
        self.round.refresh_from_db()
        self.assertEqual(self.inventory.shares_available, 19)
        self.assertEqual(MarketBotDailyUsage.objects.get(round=self.round).payout_points, sell.net_points)
        self.assertEqual(self.round.bot_daily_payout_used, sell.net_points)
        user_delta = sum(PointLedger.objects.filter(user=self.user, event_type__in=["market_buy", "market_sell"]).values_list("delta", flat=True))
        treasury_delta = sum(MarketTreasuryLedger.objects.filter(round=self.round, event_type__in=[MarketTreasuryLedger.BUY_IN, MarketTreasuryLedger.SELL_PAYOUT]).values_list("delta", flat=True))
        self.assertEqual(user_delta + treasury_delta, 0)

    def test_idempotency_returns_original_order_without_repeating_points(self):
        first, _, created = self._order(key="market-idempotency-key")
        second, balance, duplicate = self._order(key="market-idempotency-key")
        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(balance["balance"], PointAccount.objects.get(user=self.user).balance)
        self.assertEqual(MarketOrder.objects.filter(user=self.user).count(), 1)
        self.assertEqual(PointLedger.objects.filter(user=self.user, event_type="market_buy").count(), 1)

        with self.assertRaisesMessage(Exception, "idempotency key conflict"):
            self._order(user=self.other, key="market-idempotency-key")

    def test_inventory_cash_and_daily_limits_reject_without_changing_points(self):
        account_before = PointAccount.objects.get(user=self.user).balance
        self.inventory.shares_available = 0
        self.inventory.save(update_fields=["shares_available"])
        with self.assertRaisesMessage(Exception, "inventory"):
            self._order(key="market-inventory-limit")
        self.assertEqual(PointAccount.objects.get(user=self.user).balance, account_before)
        self.assertFalse(PointLedger.objects.filter(user=self.user, event_type="market_buy").exists())

        self.inventory.shares_available = self.inventory.initial_shares
        self.inventory.save(update_fields=["shares_available"])
        self.round.bot_cash_balance = 1
        self.round.bot_initial_cash = 1
        self.round.bot_max_loss = 1
        self.round.save(update_fields=["bot_cash_balance", "bot_initial_cash", "bot_max_loss"])
        with self.assertRaisesMessage(Exception, "reserve"):
            self._order(key="market-cash-limit")
        self.assertEqual(PointAccount.objects.get(user=self.user).balance, account_before)

        self.round.bot_cash_balance = 1000
        self.round.bot_initial_cash = 1000
        self.round.bot_max_loss = 1000
        self.round.daily_user_orders_limit = 1
        self.round.save(update_fields=["bot_cash_balance", "bot_initial_cash", "bot_max_loss", "daily_user_orders_limit"])
        self._order(key="market-daily-limit-1")
        with self.assertRaisesMessage(Exception, "daily order"):
            self._order(key="market-daily-limit-2")

    def test_paused_round_rejects_orders(self):
        self.round.status = MarketRound.PAUSED
        self.round.save(update_fields=["status"])
        with self.assertRaisesMessage(Exception, "paused"):
            self._order(key="market-paused-key")
        self.assertFalse(PointLedger.objects.filter(user=self.user, event_type="market_buy").exists())

    def test_user_api_exposes_quotes_and_accepts_plural_order_endpoint(self):
        self.assertEqual(
            self.client.post(
                "/api/market/orders",
                {"assetId": self.asset.pk, "side": "buy", "quantity": 1, "idempotencyKey": "guest-market-key"},
                content_type="application/json",
            ).status_code,
            401,
        )
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/market/round").status_code, 200)
        quotes = self.client.get("/api/market/quotes")
        self.assertEqual(quotes.status_code, 200)
        self.assertEqual(quotes.json()["items"][0]["code"], "KTEST")
        quote_item = quotes.json()["items"][0]
        self.assertEqual(len(quote_item["history"]), 30)
        self.assertIn("changeRate", quote_item)
        response = self.client.post(
            "/api/market/orders",
            {"assetId": self.asset.pk, "side": "buy", "quantity": 1, "idempotencyKey": "api-market-order-key"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        portfolio = self.client.get("/api/market/portfolio")
        self.assertEqual(portfolio.status_code, 200)
        self.assertIn("summary", portfolio.json())
        self.assertIn("unrealizedRate", portfolio.json()["items"][0])
        self.assertEqual(self.client.get("/api/market/orders").json()["items"][0]["source"], "user")

    def test_user_login_session_can_read_private_market_apis(self):
        response = self.client.post(
            "/api/user/login",
            {"method": "username_password", "username": self.user.username, "password": "password123"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("private", response["Cache-Control"])
        points = self.client.get("/api/points/me")
        self.assertEqual(points.status_code, 200, points.content)
        self.assertIn("no-store", points["Cache-Control"])
        portfolio = self.client.get("/api/market/portfolio")
        self.assertEqual(portfolio.status_code, 200, portfolio.content)

    def test_settlement_pays_once_closes_positions_and_restores_inventory(self):
        buy, _, _ = self._order(key="market-settlement-buy")
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.shares_available, 18)
        settled = settle_round(self.round.pk, operator="test-admin")
        self.assertEqual(settled.status, MarketRound.CLOSED)
        position = MarketPosition.objects.get(user=self.user, round=self.round, asset=self.asset)
        self.assertEqual(position.status, MarketPosition.CLOSED)
        self.assertEqual(position.shares, 0)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.shares_available, self.inventory.initial_shares)
        self.round.refresh_from_db()
        self.assertEqual(self.round.reserved_payout_points, 0)
        self.assertGreaterEqual(self.round.bot_daily_payout_used, 0)
        settlement_order = MarketOrder.objects.get(round=self.round, source=MarketOrder.SETTLEMENT)
        self.assertEqual(settlement_order.quantity, buy.quantity)
        self.assertTrue(PointLedger.objects.filter(user=self.user, event_type="market_settlement").exists())
        self.assertTrue(MarketTreasuryLedger.objects.filter(round=self.round, event_type=MarketTreasuryLedger.SETTLEMENT).exists())
        balance_after_settlement = PointAccount.objects.get(user=self.user).balance
        settle_round(self.round.pk, operator="test-admin")
        self.assertEqual(PointAccount.objects.get(user=self.user).balance, balance_after_settlement)
        self.assertEqual(MarketOrder.objects.filter(round=self.round, source=MarketOrder.SETTLEMENT).count(), 1)


class MarketAdminAPITests(TestCase):
    def login_admin(self):
        response = self.client.post(
            "/api/admin/login",
            {"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_admin_asset_decimal_and_funding_idempotency_are_audited(self):
        self.login_admin()
        asset_response = self.client.post(
            "/api/admin/market/assets",
            {"code": "KADMIN", "name": "后台股", "basePrice": "12.50"},
            content_type="application/json",
        )
        self.assertEqual(asset_response.status_code, 201, asset_response.content)
        self.assertEqual(asset_response.json()["item"]["basePrice"], "12.50")
        duplicate = self.client.post(
            "/api/admin/market/assets",
            {"code": "KADMIN", "name": "重复", "basePrice": "12.50"},
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 409)

        now = timezone.now()
        round_row = MarketRound.objects.create(
            name="后台轮次",
            status=MarketRound.DRAFT,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1),
            daily_user_stake_limit=100,
            daily_user_orders_limit=5,
            daily_user_payout_limit=100,
            max_position_shares=10,
        )
        first = self.client.post(
            f"/api/admin/market/rounds/{round_row.pk}/fund",
            {"amount": 100, "idempotencyKey": "admin-fund-idempotency"},
            content_type="application/json",
        )
        second = self.client.post(
            f"/api/admin/market/rounds/{round_row.pk}/fund",
            {"amount": 100, "idempotencyKey": "admin-fund-idempotency"},
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        round_row.refresh_from_db()
        self.assertEqual(round_row.bot_cash_balance, 100)
        self.assertEqual(MarketTreasuryLedger.objects.filter(round=round_row, event_type=MarketTreasuryLedger.ADMIN_FUND).count(), 1)


class UpcomingMarketRoundAPITests(TestCase):
    def test_upcoming_round_is_visible_but_not_tradable(self):
        now = timezone.now()
        round_row = MarketRound.objects.create(
            name="即将开始的轮次",
            status=MarketRound.OPEN,
            starts_at=now + timedelta(minutes=10),
            ends_at=now + timedelta(days=1),
            daily_user_stake_limit=100,
            daily_user_orders_limit=5,
            daily_user_payout_limit=100,
            max_position_shares=10,
        )
        response = self.client.get("/api/market/round")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item"]["id"], round_row.pk)
        self.assertFalse(response.json()["item"]["isTrading"])

        quotes = self.client.get("/api/market/quotes")
        self.assertEqual(quotes.status_code, 200)
        self.assertEqual(quotes.json()["round"]["id"], round_row.pk)
