from django.urls import path
from . import admin_views as views
urlpatterns=[
 path("api/admin/products",views.products),path("api/admin/products/<int:product_id>",views.products),
 path("api/admin/products/<int:product_id>/packages",views.packages),path("api/admin/packages/<int:package_id>",views.delete_package),
 path("api/admin/products/<int:product_id>/upload",views.direct_upload),path("api/admin/versions/<int:product_id>",views.versions),
 path("api/admin/versions/<int:version_id>/rollback",views.rollback),path("api/admin/upload-settings",views.upload_settings),
]
