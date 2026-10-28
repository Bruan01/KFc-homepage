# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    path("api/admin/stats/visits", views.visits),
]
