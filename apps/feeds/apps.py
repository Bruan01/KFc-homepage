# pyright: reportMissingImports=false
from django.apps import AppConfig


class FeedsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.feeds"
    verbose_name = "AI 信源"
