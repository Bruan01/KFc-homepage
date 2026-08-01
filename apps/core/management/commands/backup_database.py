from __future__ import annotations

from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from scripts.backup_sqlite import backup


class Command(BaseCommand):
    help = "Create a consistent SQLite backup, including WAL pages."

    def add_arguments(self, parser):
        parser.add_argument("--destination", type=Path)

    def handle(self, *args, **options):
        source = Path(settings.DATABASES["default"]["NAME"])
        if not source.is_file():
            raise CommandError(f"database not found: {source}")
        destination = options["destination"] or source.with_name(
            f"{source.name}.backup-django-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        try:
            backup(source, destination)
        except (OSError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"SQLite backup created: {destination}"))
