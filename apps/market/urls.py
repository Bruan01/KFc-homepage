from django.urls import path

from . import views

urlpatterns = [
    path("api/market/round", views.round_info),
    path("api/market/quotes", views.quotes),
    path("api/market/portfolio", views.portfolio),
    path("api/market/orders", views.orders),
    path("api/market/order", views.order),
    path("api/admin/market/rounds", views.admin_rounds),
    path("api/admin/market/assets", views.admin_assets),
    path("api/admin/market/assets/<int:asset_id>", views.admin_asset_detail),
    path("api/admin/market/inventory", views.admin_inventory),
    path("api/admin/market/rounds/<int:round_id>/fund", views.admin_fund),
    path("api/admin/market/rounds/<int:round_id>/control", views.admin_control),
    path("api/admin/market/orders", views.admin_orders),
    path("api/admin/market/treasury", views.admin_treasury),
    path("api/admin/market/audits", views.admin_audits),
]
