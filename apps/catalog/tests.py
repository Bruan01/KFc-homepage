from django.conf import settings
from django.test import TestCase

from apps.accounts.models import User, UserSubscription
from apps.catalog.models import Product, ProductPackage
from apps.downloads.models import Download
from apps.points.models import PointAccount


class CatalogAPITests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            slug="alpha",
            name="Alpha Tool",
            summary="Useful alpha utility",
            description="A detailed description",
            category="Developer",
            tags="python,tool",
            announcement="Alpha released",
            version="1.2.0",
            status="published",
            file_name="alpha.zip",
            file_path="uploads/alpha.zip",
            file_size=128,
            file_sha256="abc123",
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-02T00:00:00+00:00",
            published_at="2026-07-02T00:00:00+00:00",
        )
        ProductPackage.objects.create(
            product=self.product,
            platform="macOS",
            architecture="arm64",
            file_name="alpha-mac.zip",
            file_size=64,
            file_sha256="package-sha",
            sort_order=0,
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
        )
        Product.objects.create(
            slug="draft",
            name="Hidden Draft",
            status="draft",
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
        )
        self.user = User(username="catalog-user", email="catalog@example.com", email_verified_at="yes", created_at="2026-07-01T00:00:00+00:00")
        self.user.set_password("password123")
        self.user.save()

    def test_product_list_filters_and_includes_packages(self):
        response = self.client.get("/api/products", {"q": "alpha", "tags": "python", "category": "Developer"})
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["slug"], "alpha")
        self.assertEqual(items[0]["platforms"], ["macOS"])
        self.assertEqual(items[0]["architectures"], ["arm64"])
        self.assertEqual(len(items[0]["packages"]), 1)

    def test_product_meta_excludes_drafts(self):
        response = self.client.get("/api/products/meta")
        self.assertEqual(response.json(), {"categories": ["Developer"], "tags": ["python", "tool"]})

    def test_product_detail_has_guest_and_user_download_state(self):
        response = self.client.get("/api/products/alpha")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user_download_state"]["loggedIn"])
        self.assertEqual(response.json()["packages"][0]["download_url"], "/download/alpha?pkg=1")

        self.client.force_login(self.user)
        response = self.client.get("/api/products/alpha")
        state = response.json()["user_download_state"]
        self.assertTrue(state["loggedIn"])
        self.assertTrue(response.json()["can_download_now"])
        self.assertEqual(state["point_download_cost"], 10)
        self.assertTrue(PointAccount.objects.filter(user=self.user).exists())

        Download.objects.create(
            product=self.product,
            user=self.user,
            downloaded_at="2026-07-03T00:00:00+00:00",
        )
        response = self.client.get("/api/products/alpha")
        self.assertFalse(response.json()["can_download_now"])
        self.assertTrue(response.json()["user_download_state"]["has_downloaded"])

    def test_missing_or_draft_product_returns_404(self):
        self.assertEqual(self.client.get("/api/products/missing").status_code, 404)
        self.assertEqual(self.client.get("/api/products/draft").status_code, 404)

    def test_subscription_and_notifications(self):
        response = self.client.post("/api/subscribe", {}, content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.client.force_login(self.user)
        response = self.client.post("/api/subscribe", {}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserSubscription.objects.filter(user=self.user).exists())
        response = self.client.get("/api/user/notifications")
        self.assertTrue(response.json()["subscribed"])
        self.assertEqual(response.json()["items"][0]["product_slug"], "alpha")


class StaticPageTests(TestCase):
    def test_public_pages_and_root_assets_are_served(self):
        for path in ["/", "/login", "/account", "/points", "/store", "/cardloom", "/product/alpha", "/styles.css"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_admin_pages_require_admin_context(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login?next=/admin")
        response = self.client.post("/api/admin/login", {
            "username": settings.ADMIN_USERNAME,
            "password": settings.ADMIN_PASSWORD,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        admin_page = self.client.get("/admin")
        self.assertEqual(admin_page.status_code, 200)
        admin_body = b"".join(admin_page.streaming_content).decode()
        self.assertIn("admin-overview-card", admin_body)
        self.assertIn("admin-console-7", admin_body)
        bigscreen_page = self.client.get("/admin/bigscreen")
        self.assertEqual(bigscreen_page.status_code, 200)
        self.assertIn("admin-topbar-main", b"".join(bigscreen_page.streaming_content).decode())

        login_page = self.client.get("/login?next=/admin")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn("auth-admin-mode", b"".join(login_page.streaming_content).decode())

    def test_admin_secondary_routes_require_admin_and_render_shared_console(self):
        routes = [
            "/admin/products",
            "/admin/reviews",
            "/admin/points",
            "/admin/store",
            "/admin/imaging",
            "/admin/users",
            "/admin/settings",
        ]
        for route in routes:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 302, route)
            self.assertEqual(response["Location"], f"/login?next={route}", route)

        response = self.client.post("/api/admin/login", {
            "username": settings.ADMIN_USERNAME,
            "password": settings.ADMIN_PASSWORD,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        for route in routes:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200, route)
            body = b"".join(response.streaming_content).decode()
            self.assertIn('data-admin-route-section="', body, route)
            self.assertIn(f'href="{route}"', body, route)

    def test_market_routes_are_retired(self):
        for path in ["/market", "/admin/market", "/api/market/round", "/api/market/quotes", "/api/admin/market/rounds"]:
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_legacy_admin_pages_redirect(self):
        self.assertEqual(self.client.get("/admin/login")["Location"], "/login?next=/admin")
        self.assertEqual(self.client.get("/admin/register")["Location"], "/login?next=/admin")


class AdminProductTests(TestCase):
    def login_default_admin(self):
        response = self.client.post("/api/admin/login", {"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}, content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_create_update_versions_upload_and_delete_package(self):
        from apps.catalog.models import ProductVersion
        self.login_default_admin()
        response = self.client.post("/api/admin/products", {
            "name":"Admin Product","slug":"admin-product","status":"published",
            "platforms":["macOS"],"architectures":["ARM64"],"point_download_cost":12,
        }, content_type="application/json")
        self.assertEqual(response.status_code,201,response.content);pid=response.json()["id"]
        self.assertEqual(ProductVersion.objects.filter(product_id=pid).count(),1)
        response=self.client.put(f"/api/admin/products/{pid}",{"summary":"updated"},content_type="application/json")
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(ProductVersion.objects.filter(product_id=pid).count(),2)
        response=self.client.post(f"/api/admin/products/{pid}/upload",data=b"zip-data",content_type="application/octet-stream",HTTP_X_FILENAME="bundle.zip",HTTP_X_PLATFORM="macOS",HTTP_X_ARCHITECTURE="ARM64")
        self.assertEqual(response.status_code,200,response.content)
        package_id=ProductPackage.objects.get(product_id=pid).pk
        response=self.client.delete(f"/api/admin/packages/{package_id}")
        self.assertEqual(response.status_code,200)
        self.assertFalse(ProductPackage.objects.filter(pk=package_id).exists())

    def test_list_detail_and_upload_settings(self):
        self.login_default_admin()
        Product.objects.create(slug="one",name="One",status="draft",created_at="x",updated_at="x")
        response=self.client.get("/api/admin/products",{"q":"One"})
        self.assertEqual(response.json()["total"],1)
        pid=response.json()["items"][0]["id"]
        self.assertEqual(self.client.get(f"/api/admin/products/{pid}").status_code,200)
        response=self.client.post("/api/admin/upload-settings",{"lv2_upload_limit_mb":120,"lv3_upload_limit_mb":240},content_type="application/json")
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()["limits"]["lv2"]["mb"],120)
