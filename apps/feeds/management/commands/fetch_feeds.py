# pyright: reportMissingImports=false
# -*- coding: utf-8 -*-
"""Fetch all active RSS/Atom feeds; scheduled via launchd/cron every 2 hours."""
import time

from django.core.management.base import BaseCommand

from ...services import prune_items, run_fetch


class Command(BaseCommand):
    help = "Fetch RSS/Atom feeds into feed_items (per-source failure isolation)"

    def add_arguments(self, parser):
        parser.add_argument("--source", default=None, help="only fetch this source slug (default: all)")
        parser.add_argument("--interval", type=int, default=0, help="loop forever with this interval (seconds)")
        parser.add_argument("--prune-days", type=int, default=45, help="delete items older than N days (0 = skip)")

    def handle(self, *args, **options):
        slugs = [options["source"]] if options["source"] else None
        while True:
            results = run_fetch(slugs)
            for name, result in results.items():
                style = self.style.SUCCESS if result["status"] == "success" else self.style.WARNING
                extra = f"({result.get('count', 0)} new)" if result["status"] == "success" else result.get("message", "")[:120]
                self.stdout.write(style(f"feeds {name}: {result['status']} {extra}"))
            if options["prune_days"]:
                deleted = prune_items(options["prune_days"])
                if deleted:
                    self.stdout.write(f"pruned {deleted} stale feed items")
            if not options["interval"]:
                break
            time.sleep(options["interval"])
