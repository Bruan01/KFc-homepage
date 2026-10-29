from django.core.management.base import BaseCommand
from apps.personality.models import PersonalityJob
from apps.personality.services import process_job


class Command(BaseCommand):
    help = "将 Bangumi 热门或经典角色导入待审核候选库"

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=["recent", "classic"], default="recent")
        parser.add_argument("--works", type=int, default=10)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--subject", type=int, action="append", default=[])
        parser.add_argument("--run-now", action="store_true")

    def handle(self, *args, **options):
        job = PersonalityJob.objects.create(kind="import", requested_by="management-command", parameters={"mode": options["mode"], "work_limit": options["works"], "character_limit": options["limit"], "subject_ids": options["subject"]})
        self.stdout.write(f"Import job: {job.pk}")
        if options["run_now"]:
            process_job(job.pk)
            job.refresh_from_db()
            self.stdout.write(f"{job.status}: {job.result} {job.error}")
