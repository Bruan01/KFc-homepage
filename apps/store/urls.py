from django.urls import path

from . import listing_views, views

urlpatterns = [
    path("api/store/products", views.products),
    path("api/store/redemptions", views.redemptions),
    path("api/store/redeem", views.redeem),
    # creator shelf (kflowstore user listings)
    path("api/store/listings", listing_views.listings),
    path("api/store/listings/mine", listing_views.my_listings),
    path("api/store/listings/mine/<int:listing_id>", listing_views.my_listing_update),
    path("api/store/listings/mine/<int:listing_id>/shelf", listing_views.my_listing_shelf),
    path("api/store/listings/<int:listing_id>/redeem", listing_views.listing_redeem),
    path("api/store/purchases", listing_views.my_purchases),
    path("api/store/sales", listing_views.my_sales),
    path("api/admin/store/listings/pending", listing_views.admin_pending),
    path("api/admin/store/listings/<int:listing_id>/review", listing_views.admin_review),
    path("api/admin/store/listings/<int:listing_id>/shelf", listing_views.admin_shelf),
    path("api/admin/store/products", views.admin_products),
    path("api/admin/store/products/<int:product_id>", views.admin_products),
    path("api/admin/store/products/<int:product_id>/codes", views.admin_codes),
    path("api/admin/store/redemptions", views.admin_redemptions),
]
