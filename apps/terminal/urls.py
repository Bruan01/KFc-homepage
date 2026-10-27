# pyright: reportMissingImports=false
from django.urls import path

from . import views

urlpatterns = [
    path("api/terminal/pair/start", views.pair_start),
    path("api/terminal/pair/poll", views.pair_poll),
    path("api/terminal/pair/confirm", views.pair_confirm),
    path("api/terminal/devices", views.device_list),
    path("api/terminal/unbind", views.unbind),
    path("api/terminal/devices/revoke", views.device_revoke),
    path("api/terminal/summary", views.summary),
    path("api/terminal/checkin", views.checkin),
    path("api/terminal/textboard", views.textboard),
    path("api/terminal/firmware/latest", views.firmware_latest),
    path("api/terminal/firmware/download", views.firmware_download),
    path("api/terminal/firmware/report", views.firmware_report),
    path("api/terminal/reserve/status", views.reserve_status),
    path("api/terminal/reserve", views.reserve_create),
    path("api/terminal/reserve/cancel", views.reserve_cancel),
]
