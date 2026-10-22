import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.models import Q

from apps.community_ai.models import AssistantReplyJob, timestamp
from apps.community_ai.services import process_reply, recover_stale_jobs, touch_worker


class Command(BaseCommand):
    help = "Process explicit mentions and replies to the official AI assistant."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2)

    def handle(self, *args, **options):
        last_heartbeat = 0
        while True:
            close_old_connections()
            if time.monotonic() - last_heartbeat > 15:
                touch_worker(); last_heartbeat = time.monotonic()
            recovered = recover_stale_jobs()
            ids = list(AssistantReplyJob.objects.filter(status="queued").filter(
                Q(next_attempt_at="") | Q(next_attempt_at__lte=timestamp())).order_by("created_at").values_list("pk", flat=True)[:10])
            for job_id in ids:
                touch_worker()
                try:
                    process_reply(job_id)
                except Exception:
                    # The lease recovery path handles interrupted DB writes. Keep
                    # other jobs moving and never log provider/config exception text.
                    self.stderr.write(f"job={job_id} interrupted; awaiting lease recovery")
                    close_old_connections()
            if ids or recovered:
                self.stdout.write(f"processed={len(ids)} recovered={recovered}")
            if options["once"]:
                return
            time.sleep(max(.2, options["interval"]))
