# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    # categories
    path("api/forum/categories", views.categories),
    path("api/forum/categories/<int:category_id>/moderators", views.set_category_moderators),
    # topics
    path("api/forum/topics", views.topics),
    path("api/forum/topics/<int:topic_id>", views.topic_detail),
    path("api/forum/topics/<int:topic_id>/manage", views.manage_topic),
    path("api/forum/topics/<int:topic_id>/report", views.report_topic),
    path("api/forum/topics/create", views.create_topic),
    # replies
    path("api/forum/topics/<int:topic_id>/replies", views.create_reply),
    path("api/forum/replies/<int:reply_id>/manage", views.manage_reply),
    path("api/forum/replies/<int:reply_id>/report", views.report_reply),
    # likes
    path("api/forum/topics/<int:topic_id>/like", views.like_topic),
    path("api/forum/replies/<int:reply_id>/like", views.like_reply),
    # images
    path("api/forum/images", views.upload_image),
    path("api/forum/images/<int:image_id>", views.serve_image),
    # boosts
    path("api/forum/boosts/tiers", views.boost_tiers),
    path("api/forum/topics/<int:topic_id>/boost", views.boost_topic),
    path("api/admin/forum/reports", views.admin_forum_reports),
    path("api/admin/forum/reports/<int:report_id>/review", views.admin_review_forum_report),
    # OG share page
    path("t/<int:topic_id>", views.share_topic_page),
    path("api/forum/users/me/profile", views.my_profile),
    path("api/forum/users/me/profile/update", views.update_my_profile),
    path("api/forum/users/<str:username>", views.user_profile),
    # stats
    path("api/forum/stats", views.stats),
]
