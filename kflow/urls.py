"""Root URL configuration for KFlow."""
from django.urls import include, path

urlpatterns = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.points.urls")),
    path("", include("apps.downloads.urls")),
    path("", include("apps.core.urls")),
]
