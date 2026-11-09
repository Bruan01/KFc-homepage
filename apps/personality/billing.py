"""Charge once when a user explicitly starts a new assessment."""
import re
from django.db import transaction
from django.db.models import F

from apps.accounts.models import User
from apps.points.models import PointLedger
from apps.points.services import PointsError, apply_ledger, ensure_account, get_rules
from .configuration import ai_service_status
from .models import Assessment
from .questions import VERSION, initial_steps
from .services import config


def start_assessment(user, body):
    key = body.get('client_key', '')
    if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', key):
        raise PointsError('请刷新页面，确认费用后再开始测评')
    with transaction.atomic():
        # SQLite writer reservation precedes both idempotency and balance reads.
        User.objects.filter(pk=user.pk).update(display_name=F('display_name'))
        ledger_key = f'personality_start:{user.pk}:{key}'
        existing = PointLedger.objects.filter(idempotency_key=ledger_key).first()
        if existing:
            row = Assessment.objects.filter(pk=existing.reference_id, user=user).first()
            if not row:
                raise PointsError('上一次测评已删除，请重新开始新测评', status=410)
            return row, existing, False
        settings = config()
        if not settings.enabled:
            raise PointsError('心映暂时暂停新测评，已有档案仍可查看', status=503)
        ready, message = ai_service_status(settings)
        if not ready:
            raise PointsError(message, status=503)
        cost = get_rules()['personality_assessment_cost']
        if cost and (body.get('points_consent') is not True or type(body.get('expected_cost')) is not int or body['expected_cost'] != cost):
            raise PointsError(f'本次测评需 {cost} K 积分，请刷新服务状态并确认费用后开始')
        if Assessment.objects.filter(user=user, status='active').count() >= 10:
            raise PointsError('请先继续或删除未完成的测评', status=429)
        account = ensure_account(user)
        if account.status != 'active':
            raise PointsError('积分账户已冻结，暂时无法开始新测评', status=403)
        if account.balance < cost:
            raise PointsError(f'积分不足，本次测评需 {cost} K 积分；可先发布首条碎碎念获取积分', status=402)
        previous = Assessment.objects.filter(user=user).order_by('-created_at').first()
        previous_ids = [q['id'] for step in previous.steps for q in step['questions']] if previous else []
        row = Assessment(user=user, version=VERSION, ai_consent=True)
        row.steps = initial_steps(seed=str(row.pk), previous_ids=previous_ids)
        for step in row.steps:
            step['response_scale'] = 5
        row.steps[0]['followup_policy'] = 'bank-v1'
        row.save()
        ledger, _ = apply_ledger(user=user, event_type='personality_start', points_delta=-cost,
                                 idempotency_key=ledger_key, description='心映 MBTI 新测评',
                                 reference_type='personality_assessment', reference_id=row.pk)
        return row, ledger, True
