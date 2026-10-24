from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        from apps.core import db

        db.connect()
