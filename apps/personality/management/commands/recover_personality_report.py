import copy
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.personality.models import Assessment, PersonalityJob, timestamp
from apps.personality.provider import AnalysisUnavailable
from apps.personality.services import build_report, config, eligible_characters
from apps.personality.single_report import generate


class Command(BaseCommand):
    help = '只读检查或显式应用同档案、同上下文的已付费心映报告返回，不调用 AI'

    def add_arguments(self, parser):
        parser.add_argument('assessment_id')
        parser.add_argument('--apply', action='store_true', help='实际发布恢复结果；默认仅 dry-run')
        parser.add_argument('--operator', default='local-recovery', help='写入恢复任务的操作员标识')

    def handle(self, *args, **options):
        row = Assessment.objects.filter(pk=options['assessment_id']).first()
        if not row:
            raise CommandError('档案不存在')
        if row.status == 'completed':
            self.stdout.write('档案已完成，无需恢复；未修改数据。')
            return
        if PersonalityJob.objects.filter(assessment=row, status__in=['queued', 'processing']).exists():
            raise CommandError('档案已有活跃任务，请先等待任务结束，未修改数据。')
        previous = PersonalityJob.objects.filter(assessment=row, kind='report', status='failed').exclude(
            Q(parameters__has_key='character_only') & Q(parameters__character_only=True)).exclude(
            Q(parameters__has_key='heartline_only') & Q(parameters__heartline_only=True)).order_by('-created_at').first()
        cache = copy.deepcopy(previous.checkpoint if previous else {})
        settings = config()
        settings._report_attempt_id = 'local-recovery'

        def local_only(*args):
            raise AnalysisUnavailable('已有返回不足以恢复完整报告，需要人工检查，不会自动调用 AI。', reason='local_recovery_required')

        latest = copy.deepcopy(cache)
        def capture(phase, payload):
            latest.clear()
            latest.update(copy.deepcopy(payload))

        try:
            report = generate(row, build_report(row), settings, local_only, eligible_characters(), cache, capture)
        except (AnalysisUnavailable, ValueError) as exc:
            state = latest.get('single_report', {})
            self.stdout.write(json.dumps({
                'recoverable': False,
                'accepted_sections': len(state.get('sections', {})),
                'accepted_parts': [key for key in ('identity', 'growth', 'mechanisms', 'type_review', 'keepsake', 'match') if key in state],
                'validation_errors': state.get('validation_errors', []),
            }, ensure_ascii=False))
            raise CommandError(str(exc)) from None

        audit = report.get('audit', {}).get('single_report', {})
        recovered = audit.get('recovered_calls', [])
        summary = {
            'recoverable': True,
            'dry_run': not options['apply'],
            'assessment_id': str(row.pk),
            'title': report.get('title'),
            'sections': len(report.get('sections', [])),
            'has_character': bool(report.get('character')),
            'recovered_calls': recovered,
            'model_requests_used': row.model_requests,
            'new_model_requests': 0,
        }
        self.stdout.write(json.dumps(summary, ensure_ascii=False))
        if not options['apply']:
            self.stdout.write('dry-run 完成，未修改数据库。确认上下文后使用 --apply 显式恢复。')
            return

        with transaction.atomic():
            changed = Assessment.objects.filter(pk=row.pk, status='failed').update(
                report=report, status='completed', updated_at=timestamp())
            if not changed:
                raise CommandError('档案状态已变化，未发布恢复结果。')
            PersonalityJob.objects.create(
                kind='report', assessment=row, status='completed', phase='local_recovery',
                requested_by=options['operator'][:150],
                parameters={'recovery_only': True, 'ai': False, 'source_job_id': str(previous.pk) if previous else ''},
                result={'report_id': str(row.pk), 'recovered_calls': recovered})
            from apps.personality.operations import resolve_alerts
            resolve_alerts(row.pk)
        self.stdout.write('恢复结果已发布；原始回答、原始模型返回及请求预算均未改写。')
