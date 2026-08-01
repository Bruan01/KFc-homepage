from django.urls import path
from .views import dashboard
urlpatterns=[path("api/admin/dashboard",dashboard)]
