from django.urls import path

from . import views

urlpatterns = [
    path("imaging", views.studio_page, name="imaging-studio"),
    path("api/imaging/generations", views.create, name="imaging-create"),
    path("api/imaging/generations/<uuid:job_id>", views.detail, name="imaging-detail"),
    path("api/imaging/generations/<uuid:job_id>/image", views.image, name="imaging-image"),
    path("api/imaging/generations/<uuid:job_id>/download", views.download, name="imaging-download"),
    path("api/imaging/history", views.history, name="imaging-history"),
    path("api/admin/imaging/settings", views.admin_settings, name="admin-imaging-settings"),
    path("api/admin/imaging/providers", views.admin_providers, name="admin-imaging-providers"),
    path("api/admin/imaging/providers/create", views.admin_provider_create, name="admin-imaging-provider-create"),
    path("api/admin/imaging/providers/<int:provider_id>", views.admin_provider_detail, name="admin-imaging-provider-detail"),
    path("api/admin/imaging/providers/<int:provider_id>/test", views.admin_provider_test, name="admin-imaging-provider-test"),
    path("api/admin/imaging/providers/<int:provider_id>/recover", views.admin_provider_recover, name="admin-imaging-provider-recover"),
    # Compatibility aliases for the prior standalone imaging frontend.
    path("api/generations", views.create, name="imaging-create-compat"),
    path("api/generations/<uuid:job_id>", views.detail, name="imaging-detail-compat"),
    path("api/history", views.history, name="imaging-history-compat"),
]
