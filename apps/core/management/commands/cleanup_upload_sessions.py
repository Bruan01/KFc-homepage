from __future__ import annotations

import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.downloads.models import UploadSession


class Command(BaseCommand):
    help = "Remove expired persistent chunk-upload sessions and their temporary files."

    def handle(self, *args, **options):
        rows = list(UploadSession.objects.filter(expires_at__lt=time.time()))
        root = (settings.BASE_DIR / "uploads" / ".chunk-sessions").resolve()
        removed_files = 0
        for row in rows:
            directory = (root / row.upload_id).resolve()
            try:
                directory.relative_to(root)
            except ValueError:
                continue
            if directory.is_dir():
                shutil.rmtree(directory)
                removed_files += 1
        deleted, _ = UploadSession.objects.filter(pk__in=[row.pk for row in rows]).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {deleted} expired upload sessions and {removed_files} temporary directories."
            )
        )
