from django.conf import settings
from django.test import TestCase
from apps.catalog.models import Product


class DashboardTests(TestCase):
    def test_dashboard_requires_admin_and_returns_metrics(self):
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code,401)
        self.client.post("/api/admin/login",{"username":settings.ADMIN_USERNAME,"password":settings.ADMIN_PASSWORD},content_type="application/json")
        Product.objects.create(slug="dash",name="Dash",status="published",created_at="x",updated_at="x")
        response=self.client.get("/api/admin/dashboard")
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()["metrics"]["products_total"],1)
        self.assertTrue(response.json()["tables"])
