from django.urls import path, re_path

from . import pages, views

urlpatterns = [
    path("api/health", views.health, name="health"),
    path("admin/login", pages.legacy_admin_redirect),
    path("admin/register", pages.legacy_admin_redirect),
    path("", pages.page, {"page_path": ""}),
    path("login", pages.page, {"page_path": "login"}),
    path("account", pages.page, {"page_path": "account"}),
    path("points", pages.page, {"page_path": "points"}),
    path("store", pages.page, {"page_path": "store"}),
    path("market", pages.page, {"page_path": "market"}),
    path("admin", pages.page, {"page_path": "admin"}),
    path("admin/bigscreen", pages.page, {"page_path": "admin/bigscreen"}),
    path("cardloom", pages.page, {"page_path": "cardloom"}),
    re_path(r"^static/(?P<asset_path>.+)$", pages.static_asset),
    path("product/<slug:slug>", pages.product_page),
    path("material/<path:asset_path>", pages.material_file),
    re_path(r"^(?P<asset_path>[^/]+\.[^/]+)$", pages.static_asset),
]
