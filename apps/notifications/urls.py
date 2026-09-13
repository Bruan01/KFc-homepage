# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    path("api/notifications", views.notifications),
    path("api/notifications/unread-count", views.unread_count_view),
    path("api/notifications/mark-read", views.mark_read),
    path("api/notifications/mark-all-read", views.mark_all_read),
]
