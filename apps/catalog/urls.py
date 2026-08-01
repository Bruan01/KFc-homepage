from django.urls import path

from . import views

urlpatterns = [
    path("api/products", views.products),
    path("api/products/meta", views.products_meta),
    path("api/products/<str:key>", views.product_detail),
    path("api/subscribe", views.subscribe),
    path("api/user/notifications", views.notifications),
]
