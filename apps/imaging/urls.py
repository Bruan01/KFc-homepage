from django.urls import path

from . import views

urlpatterns = [
    path("imaging", views.studio_page, name="imaging-studio"),
    path("api/imaging/generations", views.create, name="imaging-create"),
    path("api/imaging/generations/<uuid:job_id>", views.detail, name="imaging-detail"),
    path("api/imaging/generations/<uuid:job_id>/image", views.image, name="imaging-image"),
    path("api/imaging/history", views.history, name="imaging-history"),
    # Compatibility aliases for the former FastAPI client.
    path("api/generations", views.create),
    path("api/generations/<uuid:job_id>", views.detail),
    path("api/generations/<uuid:job_id>/image", views.image),
    path("api/history", views.history),
]
