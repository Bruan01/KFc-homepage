# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    path("api/achievements", views.achievements),
    path("api/achievements/showcase", views.set_showcase),
    path("api/levels", views.levels),
    path("api/stats/overview", views.stats_overview),
    path("api/stats/contributors", views.stats_contributors),
    path("api/admin/gamification/overview", views.admin_overview),
    path("api/admin/gamification/grant", views.admin_grant),
    path("api/admin/gamification/revoke", views.admin_revoke),
    path("api/admin/gamification/recompute", views.admin_recompute),
]
