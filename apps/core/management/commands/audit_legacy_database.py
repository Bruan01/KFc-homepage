from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from scripts.django_migration_audit import audit


class Command(BaseCommand):
    help = "Run the read-only legacy SQLite schema and integrity audit."

    def add_arguments(self, parser):
        parser.add_argument("--database", type=Path)

    def handle(self, *args, **options):
        database = options["database"] or Path(settings.DATABASES["default"]["NAME"])
        if not database.is_file():
            raise CommandError(f"database not found: {database}")
        result = audit(database)
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if result["integrity"] != "ok" or result["missing_tables"]:
            raise CommandError("legacy database audit failed")
