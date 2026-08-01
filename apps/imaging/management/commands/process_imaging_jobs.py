import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.imaging.models import ImageGenerationJob
from apps.imaging.services import process_generation, recover_stale_jobs


class Command(BaseCommand):
    help = "Process queued image generation jobs and recover interrupted jobs."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="process the current queue once and exit")
        parser.add_argument("--interval", type=float, default=2.0, help="poll interval in seconds")

    def handle(self, *args, **options):
        once = bool(options["once"])
        interval = max(0.2, float(options["interval"]))
        while True:
            close_old_connections()
            recovered = recover_stale_jobs()
            job_ids = list(
                ImageGenerationJob.objects.filter(status=ImageGenerationJob.QUEUED)
                .order_by("created_at")
                .values_list("pk", flat=True)[:10]
            )
            for job_id in job_ids:
                process_generation(job_id)
            if recovered or job_ids:
                self.stdout.write(f"recovered={recovered} processed={len(job_ids)}")
            if once:
                return
            time.sleep(interval)
