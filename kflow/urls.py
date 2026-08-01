"""Root URL configuration for KFlow."""
from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
]
