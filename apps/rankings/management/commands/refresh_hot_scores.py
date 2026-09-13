# pyright: reportMissingImports=false
"""Recompute forum hot scores; run hourly via cron."""
from django.core.management.base import BaseCommand

from apps.forum.services import refresh_hot_scores


class Command(BaseCommand):
    help = "Recompute forum topic hot scores and expire finished boosts"

    def handle(self, *args, **options):
        updated = refresh_hot_scores()
        self.stdout.write(self.style.SUCCESS(f"refreshed hot scores for {updated} topics"))
        try:
            from apps.gamification.services import refresh_user_stats_table, refresh_all_levels

            stats = refresh_user_stats_table()
            changed = refresh_all_levels()
            self.stdout.write(self.style.SUCCESS(f"gamification: stats {stats}, levels changed {changed}"))
        except Exception as exc:  # gamification 故障不阻断热度重算
            self.stdout.write(self.style.WARNING(f"gamification refresh skipped: {exc}"))
