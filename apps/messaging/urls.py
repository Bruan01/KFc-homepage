from django.urls import path
from . import views

urlpatterns = [path("api/messages", views.inbox),
               path("api/messages/<str:username>", views.thread),
               path("api/messages/<str:username>/read", views.mark_read)]
