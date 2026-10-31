from functools import wraps
import time

from django.db import OperationalError, transaction
from django.db.models import F
from django.utils import timezone

from .configuration import ai_service_status
from .models import Assessment, DailyUsage
from .provider import AnalysisUnavailable

REPORT_REQUEST_LIMIT = 3
RETRY_COOLDOWN_SECONDS = 60
NON_RETRYABLE_REASONS = {'configuration', 'authentication', 'not_found', 'service_unavailable', 'internal'}


def daily_request_limit(settings):
    return settings.daily_reports_per_user * REPORT_REQUEST_LIMIT


def retry_sqlite_locked(operation):
    @wraps(operation)
    def call(*args, **kwargs):
        for attempt in range(10):
            try:
                return operation(*args, **kwargs)
            except OperationalError as exc:
                if 'locked' not in str(exc).lower() or attempt == 9:
                    raise
                time.sleep(0.05 * (attempt + 1))
    return call


@retry_sqlite_locked
def reserve_report_request(assessment, settings):
    day = timezone.localdate().isoformat()
    with transaction.atomic():
        reserved = Assessment.objects.filter(pk=assessment.pk, model_requests__lt=REPORT_REQUEST_LIMIT).update(model_requests=F('model_requests') + 1)
        if not reserved:
            raise AnalysisUnavailable('本次测评的模型请求预算已用完，已反馈管理员，回答已保存。', reason='assessment_budget')
        usage, _ = DailyUsage.objects.get_or_create(user_id=assessment.user_id, day=day)
        if not DailyUsage.objects.filter(pk=usage.pk, model_requests__lt=daily_request_limit(settings)).update(model_requests=F('model_requests') + 1):
            raise AnalysisUnavailable('今天的模型请求预算已用完，回答已保存，请明天再试。', reason='daily_budget')
    assessment.model_requests += 1


def cooldown_remaining(job):
    if not job or not job.parameters.get('failure_reason'):
        return 0
    try:
        failed_at = timezone.datetime.fromisoformat(job.updated_at)
        remaining = RETRY_COOLDOWN_SECONDS - (timezone.now() - failed_at).total_seconds()
        return max(0, int(remaining + 0.999))
    except (TypeError, ValueError):
        return 0


def retry_state(row, settings, job=None):
    usage = DailyUsage.objects.filter(user_id=row.user_id, day=timezone.localdate().isoformat()).first()
    daily_used = usage.model_requests if usage else 0
    result = {
        'can_retry': row.status == 'failed',
        'retry_after': 0,
        'retry_block_reason': '',
        'model_requests_used': row.model_requests,
        'model_request_limit': REPORT_REQUEST_LIMIT,
        'daily_model_requests_used': daily_used,
        'daily_model_request_limit': daily_request_limit(settings),
    }
    if row.status != 'failed':
        result['can_retry'] = False
        return result
    reason = (job.parameters.get('failure_reason') if job else '') or ''
    block = ''
    if not row.ai_consent:
        block = 'consent_required'
    elif reason in NON_RETRYABLE_REASONS or not ai_service_status(settings)[0]:
        block = reason if reason in NON_RETRYABLE_REASONS else 'service_unavailable'
    elif row.model_requests >= REPORT_REQUEST_LIMIT:
        block = 'assessment_budget'
    elif daily_used >= daily_request_limit(settings):
        block = 'daily_budget'
    else:
        remaining = cooldown_remaining(job)
        if remaining:
            block = 'cooldown'
            result['retry_after'] = remaining
    result['can_retry'] = not block
    result['retry_block_reason'] = block
    return result


def failure_notice(row, settings, job):
    state = retry_state(row, settings, job)
    reason = state['retry_block_reason']
    if reason == 'cooldown':
        return f"分析暂未成功，请 {state['retry_after']} 秒后再试；回答已保存。"
    if reason == 'assessment_budget':
        return '本次分析的请求预算已用完，已反馈管理员，回答已保存。'
    if reason == 'daily_budget':
        return '今天的模型请求预算已用完，回答已保存，请明天再试。'
    if reason in NON_RETRYABLE_REASONS:
        return '分析服务需要管理员处理，已反馈管理员，回答已保存。'
    return (job.error if job else '') or '分析未完成，回答已保存。'
