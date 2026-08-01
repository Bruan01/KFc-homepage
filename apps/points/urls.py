from django.urls import path
from . import views

urlpatterns = [
    path("api/points/me", views.me),
    path("api/points/rules", views.rules),
    path("api/points/ledger", views.ledger),
    path("api/points/download-entitlements", views.entitlements),
    path("api/points/redeem-download", views.redeem),
    path("api/admin/points/settings", views.admin_settings),
    path("api/admin/points/accounts", views.admin_accounts),
    path("api/admin/points/adjust", views.adjust),
    path("api/admin/points/freeze", views.freeze),
    path("api/admin/points/unfreeze", views.unfreeze),
]
