from django.urls import path
from .views import community, dashboard
urlpatterns=[
    path("api/admin/dashboard",dashboard),
    path("api/admin/dashboard/community",community),
]
