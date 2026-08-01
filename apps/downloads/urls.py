from django.urls import path
from . import views

urlpatterns = [
    path("api/user/history", views.history),
    path("api/user/download-quota", views.quota),
    path("api/user/requests", views.requests),
    path("api/products/<str:key>/request-download", views.request_download),
    path("api/admin/download-requests", views.admin_requests),
    path("api/admin/download-requests/<int:request_id>/approve", lambda request, request_id: views.review_request(request, request_id, "approved")),
    path("api/admin/download-requests/<int:request_id>/reject", lambda request, request_id: views.review_request(request, request_id, "rejected")),
    path("api/admin/products/<int:product_id>/upload-sessions", views.upload_session_create),
    path("api/admin/upload-sessions/<str:upload_id>/complete", views.upload_complete),
    path("api/admin/upload-sessions/<str:upload_id>/chunks/<int:index>", views.upload_chunk),
    path("download/<str:key>", views.download),
]
