# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    # categories
    path("api/forum/categories", views.categories),
    # topics
    path("api/forum/topics", views.topics),
    path("api/forum/topics/<int:topic_id>", views.topic_detail),
    path("api/forum/topics/create", views.create_topic),
    # replies
    path("api/forum/topics/<int:topic_id>/replies", views.create_reply),
    # likes
    path("api/forum/topics/<int:topic_id>/like", views.like_topic),
    path("api/forum/replies/<int:reply_id>/like", views.like_reply),
    # images
    path("api/forum/images", views.upload_image),
    path("api/forum/images/<int:image_id>", views.serve_image),
    # boosts
    path("api/forum/boosts/tiers", views.boost_tiers),
    path("api/forum/topics/<int:topic_id>/boost", views.boost_topic),
    # OG share page
    path("t/<int:topic_id>", views.share_topic_page),
    path("api/forum/users/me/profile", views.my_profile),
    path("api/forum/users/me/profile/update", views.update_my_profile),
    path("api/forum/users/<str:username>", views.user_profile),
    # stats
    path("api/forum/stats", views.stats),
]
