# pyright: reportMissingImports=false
"""Crawl external vibecoding project rankings; run daily via cron."""
from django.core.management.base import BaseCommand

from ...services import run_crawl


class Command(BaseCommand):
    help = "Crawl external vibecoding rankings (GitHub Trending via API, ProductHunt, CN community)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            choices=["github", "producthunt", "cn_community"],
            default=None,
            help="only crawl this source (default: all)",
        )

    def handle(self, *args, **options):
        source = options.get("source")
        results = run_crawl([source] if source else None)
        for name, result in results.items():
            style = self.style.SUCCESS if result["status"] == "success" else self.style.WARNING
            self.stdout.write(style(f"{name}: {result['status']} ({result.get('count', 0)} items) {result.get('message', '')}"))
