# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    path("api/learn/glossary", views.glossary),
    path("api/learn/glossary/<str:slug>", views.glossary_detail),
    path("api/learn/tutorials", views.tutorials),
    path("api/learn/tutorials/<str:slug>", views.tutorial_detail),
    path("api/learn/complete", views.complete),
]
