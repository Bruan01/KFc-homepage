# pyright: reportMissingImports=false
"""Analyze top external projects: summaries, tags, design-analysis (LLM when available)."""
from django.core.management.base import BaseCommand

from ...analysis import analyze_top_projects, snapshot_metrics


class Command(BaseCommand):
    help = "Generate summaries/tags/analysis for top external projects"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="re-analyze even if recent")
        parser.add_argument("--per-source", type=int, default=10, help="top N per source (default 10)")

    def handle(self, *args, **options):
        snapshot_metrics()
        analyzed = analyze_top_projects(force=options["force"], per_source=options["per_source"])
        self.stdout.write(self.style.SUCCESS(f"analyzed {analyzed} projects (source: llm when CPA configured, else rules)"))
