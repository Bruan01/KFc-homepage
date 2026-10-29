import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from apps.personality.transfer import export_catalog


class Command(BaseCommand):
    help = "导出角色资料、图片链接、审核档案和经典名单，不包含用户或密钥"

    def add_arguments(self, parser):
        parser.add_argument("destination")

    def handle(self, *args, **options):
        path = Path(options["destination"])
        if path.exists():
            raise CommandError("目标文件已存在，请选择新的文件名")
        path.write_text(json.dumps(export_catalog(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"Catalog exported: {path}")
