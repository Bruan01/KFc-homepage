# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    path("api/feeds/sources", views.feeds_sources),
    path("api/feeds/sources/", views.feeds_sources),
    path("api/feeds/items", views.feeds_items),
    path("api/feeds/items/", views.feeds_items),
    path("api/feeds/hot", views.feeds_hot),
    path("api/feeds/hot/", views.feeds_hot),
    path("api/feeds/ask", views.feeds_ask),
    path("api/feeds/ask/", views.feeds_ask),
]
