import json
from pathlib import Path
from django.core.management.base import BaseCommand
from apps.personality.models import Character
from apps.personality.transfer import import_catalog


class Command(BaseCommand):
    help = "安装随代码发布的首批角色档案，保留任何已有审核、排除或编辑内容"

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / "data" / "starter-characters.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        existing = {row.source_id: row for row in Character.objects.filter(source_id__in=[r["source_id"] for r in payload["characters"]])}
        payload["characters"] = [row for row in payload["characters"] if row["source_id"] not in existing or (existing[row["source_id"]].status == "candidate" and not existing[row["source_id"]].profile)]
        result = import_catalog(payload) if payload["characters"] else {"imported": 0, "preserved": len(existing)}
        self.stdout.write(f"Starter catalog: {result['imported']} installed, existing edits preserved")
