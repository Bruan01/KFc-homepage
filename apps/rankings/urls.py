# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    path("api/rankings/site", views.site_rankings),
    path("api/rankings/creators", views.creator_rankings),
    path("api/rankings/external", views.external_rankings),
    path("api/rankings/external/<int:project_id>", views.external_project_detail),
    path("api/rankings/external/<int:project_id>/vote", views.vote_external_project),
    path("api/rankings/trends", views.external_trends),
]
