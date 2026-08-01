from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.test import TestCase

from apps.accounts.models import AdminAccount
from apps.catalog.models import Product
from .models import ProductDeleteRequest, PublishRequest


class PublishingTests(TestCase):
    def admin(self, username, level):
        return AdminAccount.objects.create(username=username,password_hash=make_password("password123"),email=f"{username}@example.com",created_at="2026-08-01T00:00:00+00:00",created_by="admin",admin_level=level)

    def login(self, username, password="password123"):
        response=self.client.post("/api/admin/login",{"username":username,"password":password},content_type="application/json")
        self.assertEqual(response.status_code,200,response.content)

    def test_publish_request_and_weighted_vote(self):
        self.admin("requester",1);self.admin("reviewer",2)
        product=Product.objects.create(slug="review",name="Review",status="draft",file_path="uploads/review.zip",created_by="requester",created_at="x",updated_at="x")
        self.login("requester")
        response=self.client.post("/api/admin/publish-requests",{"product_id":product.pk},content_type="application/json")
        self.assertEqual(response.status_code,200,response.content);request_id=response.json()["request_id"]
        self.client.post("/api/admin/logout",{},content_type="application/json");self.login("reviewer")
        response=self.client.post(f"/api/admin/publish-requests/{request_id}/vote",{"vote":"approve","note":"ship"},content_type="application/json")
        self.assertEqual(response.status_code,200,response.content);self.assertEqual(response.json()["status"],"approved")
        product.refresh_from_db();self.assertEqual(product.status,"published")

    def test_delete_request_requires_owner_approval(self):
        self.admin("worker",2)
        product=Product.objects.create(slug="owned",name="Owned",status="draft",created_by=settings.ADMIN_USERNAME,created_at="x",updated_at="x")
        self.login("worker")
        response=self.client.delete(f"/api/admin/products/{product.pk}")
        self.assertEqual(response.status_code,202,response.content);request_id=response.json()["request_id"]
        self.client.post("/api/admin/logout",{},content_type="application/json")
        response=self.client.post("/api/admin/login",{"username":settings.ADMIN_USERNAME,"password":settings.ADMIN_PASSWORD},content_type="application/json")
        self.assertEqual(response.status_code,200)
        inbox=self.client.get("/api/admin/inbox").json();self.assertEqual(inbox["delete_requests"][0]["id"],request_id)
        response=self.client.post(f"/api/admin/delete-requests/{request_id}/approve",{},content_type="application/json")
        self.assertEqual(response.status_code,200,response.content);self.assertFalse(Product.objects.filter(pk=product.pk).exists())
