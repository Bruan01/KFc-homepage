import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from apps.personality.transfer import import_catalog


class Command(BaseCommand):
    help = "合并导入心映角色数据包，默认保留服务器已有的已审核与排除档案"

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--replace-reviewed", action="store_true", help="明确覆盖已有审核与排除档案")

    def handle(self, *args, **options):
        try:
            path = Path(options["source"])
            if path.stat().st_size > 25 * 1024 * 1024:
                raise ValueError("角色数据包超过 25 MB")
            result = import_catalog(json.loads(path.read_text(encoding="utf-8-sig")), replace_reviewed=options["replace_reviewed"])
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result))
