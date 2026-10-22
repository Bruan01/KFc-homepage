from django.urls import path
from . import views

urlpatterns = [
    path("api/admin/community-ai/settings", views.assistant_settings),
    path("api/admin/community-ai/test", views.test_reply),
    path("api/admin/community-ai/records", views.reply_records),
    path("api/admin/community-ai/records/<uuid:job_id>/retry", views.retry_reply),
]
