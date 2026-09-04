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
    # stats
    path("api/forum/stats", views.stats),
]
