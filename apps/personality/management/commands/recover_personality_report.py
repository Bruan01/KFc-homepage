import json

from django.core.management.base import BaseCommand, CommandError

from apps.personality.recovery import recover_assessment


class Command(BaseCommand):
    help = '只读检查或显式应用同档案、同上下文的已付费心映报告返回，不调用 AI'

    def add_arguments(self, parser):
        parser.add_argument('assessment_id')
        parser.add_argument('--apply', action='store_true', help='实际发布恢复结果；默认仅 dry-run')
        parser.add_argument('--operator', default='local-recovery', help='写入恢复任务的操作员标识')

    def handle(self, *args, **options):
        try:
            result = recover_assessment(options['assessment_id'], apply=options['apply'], operator=options['operator'])
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        if result.get('already_completed'):
            self.stdout.write('档案已完成，无需恢复；未修改数据。')
            return
        self.stdout.write(json.dumps(result, ensure_ascii=False))
        if not options['apply']:
            self.stdout.write('dry-run 完成，未修改数据库。确认上下文后使用 --apply 显式恢复。')
            return
        self.stdout.write('恢复结果已发布；原始回答、原始模型返回及请求预算均未改写。')
