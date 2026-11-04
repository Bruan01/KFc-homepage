from django.conf import settings
from django.test import Client, TestCase

from apps.catalog.models import Product
from apps.downloads.models import Download, DownloadRequest
from .models import AdminAccount, User, UserSubscription


class AdminUserFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.real = User.objects.create(username="community_guest_real", display_name="真实昵称", email="real@example.com", created_at="2026-01-01")
        cls.system = User.objects.create(username="generated", is_system_generated=True, created_at="2026-02-01")
        cls.admin = User.objects.create(username="filter_admin", created_at="2026-02-01")
        cls.owner = User.objects.create(username=settings.ADMIN_USERNAME, created_at="2026-02-01")
        AdminAccount.objects.create(username=cls.admin.username, admin_level=1, created_at="x")
        UserSubscription.objects.create(user=cls.real, created_at="x")
        product = Product.objects.create(slug="filter-product", name="测试", created_at="x", updated_at="x")
        for _ in range(2):
            Download.objects.create(user=cls.real, product=product, downloaded_at="x")
        for _ in range(3):
            DownloadRequest.objects.create(user=cls.admin, product=product, created_at="x")

    def setUp(self):
        self.admin_client = Client()
        session = self.admin_client.session
        session.update({"admin_username": "reviewer", "admin_level": 1})
        session.save()

    def rows(self, **params):
        response = self.admin_client.get("/api/admin/users", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_source_filter_uses_marker_and_combines_search(self):
        data = self.rows(account_type="real")
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["count"], 3)
        self.assertIn(self.real.pk, [row["id"] for row in data["items"]])
        self.assertEqual([row["id"] for row in self.rows(account_type="system")["items"]], [self.system.pk])
        for query in ["真实昵称", "real@example", str(self.real.pk)]:
            self.assertEqual([row["id"] for row in self.rows(q=query, account_type="real")["items"]], [self.real.pk])
        self.assertEqual(User.objects.count(), 4)

    def test_role_and_subscription_filters(self):
        self.assertEqual({row["id"] for row in self.rows(role="admin")["items"]}, {self.admin.pk, self.owner.pk})
        self.assertEqual({row["id"] for row in self.rows(role="member", subscribed="yes")["items"]}, {self.real.pk})
        self.assertEqual(self.rows(account_type="system", subscribed="yes")["items"], [])

    def test_sort_order_and_aggregate_counts(self):
        self.assertEqual(self.rows(sort="oldest")["items"][0]["id"], self.real.pk)
        self.assertEqual(self.rows(sort="newest")["items"][0]["id"], self.owner.pk)
        most_downloads = self.rows(sort="downloads_desc")["items"][0]
        self.assertEqual((most_downloads["id"], most_downloads["download_count"]), (self.real.pk, 2))
        self.assertEqual(self.rows(sort="requests_desc")["items"][0]["id"], self.admin.pk)
        for sort in ("username", "id_asc", "id_desc", "downloads_asc", "requests_asc"):
            self.assertEqual(len(self.rows(sort=sort)["items"]), 4)

    def test_invalid_filters_and_guest_are_rejected(self):
        for params in [{"sort": "password"}, {"account_type": "fake"}, {"role": "invalid"}, {"subscribed": "invalid"}]:
            self.assertEqual(self.admin_client.get("/api/admin/users", params).status_code, 400)
        self.assertEqual(Client().get("/api/admin/users", {"account_type": "real"}).status_code, 401)
