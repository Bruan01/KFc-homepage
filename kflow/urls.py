"""Root URL configuration for KFlow."""
from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
]
