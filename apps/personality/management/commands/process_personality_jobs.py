import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.models import Case, IntegerField, When

from apps.personality.models import PersonalityJob, PersonalitySettings, timestamp
from apps.personality.services import process_job, recover_jobs


class Command(BaseCommand):
    help = "处理心映追问、报告、角色导入与人格草稿任务"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2)

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            PersonalitySettings.objects.get_or_create(pk=1)
            PersonalitySettings.objects.filter(pk=1).update(worker_last_seen_at=timestamp())
            recover_jobs()
            processed = 0
            for _ in range(20):
                # Re-read priorities between jobs so an interview need not wait
                # behind an entire previously selected catalog batch.
                pk = PersonalityJob.objects.filter(status="queued").order_by(
                    Case(When(kind='followup', then=0), When(kind='report', then=1), default=2, output_field=IntegerField()),
                    'created_at').values_list('pk', flat=True).first()
                if pk is None:
                    break
                process_job(pk); processed += 1
            if options["once"]:
                self.stdout.write(f"Processed {processed} personality jobs")
                return
            time.sleep(max(0.5, options["interval"]))
