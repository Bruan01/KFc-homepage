# pyright: reportMissingImports=false
from django.apps import AppConfig


class StatsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.stats"
    verbose_name = "访问统计"
