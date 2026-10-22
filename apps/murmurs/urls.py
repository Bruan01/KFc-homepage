from django.urls import path
from . import views

urlpatterns = [
    path("api/murmurs", views.posts),
    path("api/murmurs/session", views.session),
    path("api/murmurs/appeals", views.submit_appeal),
    path("api/murmurs/appeals/context", views.appeal_context),
    path("api/murmurs/blocks", views.blocks),
    path("api/murmurs/<int:post_id>", views.post_detail),
    path("api/murmurs/<int:post_id>/like", views.like),
    path("api/murmurs/<int:post_id>/pin", views.pin_post),
    path("api/murmurs/<int:post_id>/comments", views.comments),
    path("api/murmurs/<int:post_id>/report", views.report),
    path("api/murmurs/comments/<int:comment_id>", views.comment_detail),
    path("api/murmurs/comments/<int:comment_id>/report", views.report_comment),
    path("api/admin/murmurs/reports", views.admin_reports),
    path("api/admin/murmurs/reports/<int:report_id>/review", views.review_report),
    path("api/admin/murmurs/pending-count", views.pending_count),
    path("api/admin/murmurs/appeals", views.admin_appeals),
    path("api/admin/murmurs/appeals/<int:appeal_id>/review", views.review_appeal),
]
