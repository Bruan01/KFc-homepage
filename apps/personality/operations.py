"""Operational signals contain job metadata, never private answers or prompts."""
import logging
from datetime import timedelta

from django.db import DatabaseError, transaction
from django.utils import timezone

from .configuration import ai_service_status, worker_alive
from .models import OperationalAlert, PersonalityJob, timestamp

logger = logging.getLogger(__name__)
SAVED_NOTICE = '回答已保存，不用重做，可以稍后回来。'


def delayed(job, settings):
    if job.status not in {'queued', 'processing'}:
        return False
    # A provider may perform a bounded second request for a truncated response.
    seconds = 180 if job.status == 'queued' else max(300, settings.timeout_seconds*2+60)
    try:
        value = timezone.datetime.fromisoformat(job.updated_at)
        return timezone.is_aware(value) and value < timezone.now()-timedelta(seconds=seconds)
    except (ValueError, TypeError):
        return False


def flag_job(job, code):
    if not job.assessment_id or job.kind not in {'report', 'followup'}:
        return False
    try:
        with transaction.atomic():
            alert, created = OperationalAlert.objects.get_or_create(job=job, defaults={'code': code})
            if not created and (alert.code != code or alert.status == 'resolved'):
                OperationalAlert.objects.filter(pk=alert.pk).update(code=code, status='open', acknowledged_by='', resolved_at='')
        return True
    except DatabaseError:
        logger.warning('心映运行提醒未能保存')
        return False


def resolve_alerts(assessment_id):
    OperationalAlert.objects.filter(job__assessment_id=assessment_id).exclude(status='resolved').update(status='resolved', resolved_at=timestamp())


def scan_alerts(settings):
    # Also runs from the admin page: it detects stopped workers even when no
    # worker is available to run the scanner. No user report polling is needed.
    jobs = PersonalityJob.objects.filter(kind__in=['report', 'followup'], assessment__isnull=False,
        status__in=['queued', 'processing']).order_by('updated_at')[:200]
    existing = set(OperationalAlert.objects.filter(code='stalled').exclude(status='resolved').values_list('job_id', flat=True))
    for job in jobs:
        if delayed(job, settings):
            flag_job(job, 'stalled')
        elif job.pk in existing:
            OperationalAlert.objects.filter(job=job, code='stalled').exclude(status='resolved').update(status='resolved', resolved_at=timestamp())
    # Include failures that predate this dashboard, one latest failure per
    # currently failed assessment. Superseded attempts are not new alerts.
    seen = set()
    for job in PersonalityJob.objects.filter(kind='report', status='failed', assessment__status='failed').order_by('-created_at')[:200]:
        if job.assessment_id not in seen:
            flag_job(job, 'failed')
            seen.add(job.assessment_id)
    for job in PersonalityJob.objects.filter(kind='report', status='completed', result__notification_pending=True,
            assessment__status='completed').select_related('assessment')[:50]:
        if notify_report_completed(job.assessment):
            PersonalityJob.objects.filter(pk=job.pk, status='completed', result__notification_pending=True).update(
                result={**job.result, 'notification_pending': False})


def report_signal(job, settings):
    is_delayed = bool(job and delayed(job, settings))
    recorded = flag_job(job, 'failed' if job.status == 'failed' else 'stalled') if job and (is_delayed or job.status == 'failed') else False
    return {'is_delayed': is_delayed, 'reported_to_admin': recorded,
            'notice': SAVED_NOTICE+(' 已反馈后台处理。' if recorded else '') if is_delayed or (job and job.status == 'failed') else ''}


def readiness(settings):
    from .services import eligible_characters
    from .catalog import validate_profile
    ai_ready, _ = ai_service_status(settings)
    count = 0
    for character in eligible_characters().iterator(chunk_size=100):
        try:
            validate_profile(character.profile, character)
            count += 1
        except ValueError:
            continue
    checks = [
        {'key': 'enabled', 'name': '新测评入口', 'ready': settings.enabled, 'detail': '已开放' if settings.enabled else '当前处于维护状态，可在高级设置中开放', 'href': '/admin/personality/settings'},
        {'key': 'ai', 'name': 'AI 分析服务', 'ready': ai_ready, 'detail': '当前连接检查通过' if ai_ready else '请完善密钥、启用 AI，并检查已保存的连接', 'href': '/admin/personality/settings'},
        {'key': 'worker', 'name': '后台任务服务', 'ready': worker_alive(settings), 'detail': '近期收到心跳' if worker_alive(settings) else '未收到近期心跳，请检查 process_personality_jobs 服务', 'href': ''},
        {'key': 'characters', 'name': '完整角色档案', 'ready': count > 0, 'detail': f'{count} 个角色可匹配' if count else '请先发布至少一个六维完整的角色档案', 'href': '/admin/personality?stage=approved'},
    ]
    return {'ready': all(item['ready'] for item in checks), 'checks': checks, 'checked_at': timestamp()}


def notify_report_completed(row):
    from apps.notifications.models import Notification
    try:
        with transaction.atomic():
            Notification.objects.get_or_create(recipient_id=row.user_id, type='system',
                title='你的人格共鸣档案已生成', link=f'/personality/report/{row.pk}',
                defaults={'body': '来看看这次的人格探索结果。'+('与你共鸣的动漫角色也已揭晓。' if row.report.get('character') else '')})
        return True
    except DatabaseError:
        logger.warning('心映报告完成通知未能保存')
        return False
