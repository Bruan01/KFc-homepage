from django.urls import path

from . import views

urlpatterns = [
    path("api/store/products", views.products),
    path("api/store/redemptions", views.redemptions),
    path("api/store/redeem", views.redeem),
    path("api/admin/store/products", views.admin_products),
    path("api/admin/store/products/<int:product_id>", views.admin_products),
    path("api/admin/store/products/<int:product_id>/codes", views.admin_codes),
    path("api/admin/store/redemptions", views.admin_redemptions),
]
