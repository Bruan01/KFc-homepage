# pyright: reportMissingImports=false
"""Hourly gamification refresh: stats snapshots + level recompute.

Also invoked from the rankings refresh entry so the existing cron covers it.
"""
from django.core.management.base import BaseCommand

from ...services import refresh_user_stats_table, refresh_all_levels


class Command(BaseCommand):
    help = "Refresh user stats snapshots and recompute trust levels"

    def handle(self, *args, **options):
        stats = refresh_user_stats_table()
        changed = refresh_all_levels()
        self.stdout.write(self.style.SUCCESS(f"stats refreshed: {stats}; levels changed: {changed}"))
