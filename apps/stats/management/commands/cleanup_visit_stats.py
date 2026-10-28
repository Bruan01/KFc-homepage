# pyright: reportMissingImports=false
from django.core.management.base import BaseCommand

from apps.stats.services import cleanup


class Command(BaseCommand):
    help = "Delete visit statistics older than the retention window (default 90 days)"

    def add_arguments(self, parser):
        parser.add_argument("--keep-days", type=int, default=90, help="retention window in days")

    def handle(self, *args, **options):
        deleted = cleanup(options["keep_days"])
        summary = ", ".join(f"{table}={count}" for table, count in deleted.items())
        self.stdout.write(self.style.SUCCESS(f"visit stats cleaned: {summary}"))
