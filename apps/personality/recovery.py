import copy
import json

from django.db import transaction
from django.db.models import Q

from .models import Assessment, PersonalityJob, timestamp
from .provider import AnalysisUnavailable


def recover_assessment(assessment_id, *, apply=False, operator='local-recovery'):
    from .services import build_report, config, eligible_characters
    from .single_report import generate

    row = Assessment.objects.filter(pk=assessment_id).first()
    if not row:
        raise ValueError('档案不存在')
    if row.status == 'completed':
        return {'recoverable': False, 'already_completed': True, 'assessment_id': str(row.pk), 'new_model_requests': 0}
    if PersonalityJob.objects.filter(assessment=row, status__in=['queued', 'processing']).exists():
        raise ValueError('档案已有活跃任务，请先等待任务结束，未修改数据。')
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
        raise ValueError(str(exc)) from None

    recovered = report.get('audit', {}).get('single_report', {}).get('recovered_calls', [])
    summary = {
        'recoverable': True,
        'dry_run': not apply,
        'assessment_id': str(row.pk),
        'title': report.get('title'),
        'sections': len(report.get('sections', [])),
        'has_character': bool(report.get('character')),
        'recovered_calls': recovered,
        'model_requests_used': row.model_requests,
        'new_model_requests': 0,
    }
    if not apply:
        return summary

    with transaction.atomic():
        changed = Assessment.objects.filter(pk=row.pk, status='failed').update(
            report=report, status='completed', updated_at=timestamp())
        if not changed:
            raise ValueError('档案状态已变化，未发布恢复结果。')
        PersonalityJob.objects.create(
            kind='report', assessment=row, status='completed', phase='local_recovery',
            requested_by=operator[:150],
            parameters={'recovery_only': True, 'ai': False, 'source_job_id': str(previous.pk) if previous else ''},
            result={'report_id': str(row.pk), 'recovered_calls': recovered})
        from .operations import resolve_alerts
        resolve_alerts(row.pk)
    return summary
