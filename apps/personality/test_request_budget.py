import copy
import io
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.db.models import Q
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from . import tests as fixtures
from .analysis import source_answers, validate_match
from .budget import reserve_report_request
from .models import AnalysisCall, Assessment, Character, DailyUsage, PersonalityJob, PersonalitySettings, timestamp
from .provider import AnalysisUnavailable
from .services import build_report, config, eligible_characters, process_job, recover_jobs
from .single_report import anonymous_candidates, candidate_pool, compact_answers, generate, replay_paid_results, returned_result
from .test_analysis import match_fixture
from .test_single_report import SingleReportJourneyTests


class EvidenceCompatibilityTests(SimpleTestCase):
    def test_single_strings_normalize_but_unknown_comma_and_cross_role_ids_stay_rejected(self):
        role = SimpleNamespace(pk=1)
        result = match_fixture(role)
        pool = [
            {'id': 1, 'references': {'empathy': '所选角色依据'}},
            {'id': 2, 'references': {'other_role_only': '其它角色依据'}},
        ]
        source = {'open-conflict': {'kind': 'open', 'note': '真实回答', 'skipped': False}}
        for group in ('similarities', 'differences'):
            for item in result[group]:
                item['user_evidence'] = 'open-conflict'
                item['character_evidence'] = 'empathy'
        selected, clean = validate_match(result, pool, source)
        self.assertEqual(selected['id'], 1)
        self.assertEqual(clean['similarities'][0]['user_evidence'], ['open-conflict'])
        self.assertEqual(clean['similarities'][0]['character_evidence'], ['empathy'])
        for value in ('unknown', 'open-conflict,base-IE-9'):
            invalid = copy.deepcopy(result)
            invalid['similarities'][0]['user_evidence'] = value
            with self.assertRaises(ValueError):
                validate_match(invalid, pool, source)
        invalid = copy.deepcopy(result)
        invalid['similarities'][0]['character_evidence'] = 'other_role_only'
        with self.assertRaises(ValueError) as caught:
            validate_match(invalid, pool, source)
        self.assertEqual(caught.exception.issues[0]['code'], 'unknown_evidence')


class RequestBudgetAndRecoveryTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    character = fixtures.PersonalityTests.character
    finish = fixtures.PersonalityTests.finish
    create = fixtures.PersonalityTests.create
    public_finish = SingleReportJourneyTests.public_finish
    combined = SingleReportJourneyTests.combined
    submit = SingleReportJourneyTests.submit
    prepare = SingleReportJourneyTests.prepare

    def age(self, job):
        PersonalityJob.objects.filter(pk=job.pk).update(updated_at='2000-01-01T00:00:00+00:00')
        job.refresh_from_db()

    def test_cross_task_limit_and_cooldown_cannot_be_reset_by_manual_retries(self):
        row = self.prepare()
        def incomplete(settings, prompt, payload):
            result = self.combined(row, payload)
            result['match']['similarities'][0]['user_evidence'] = 999
            return result
        with patch('apps.personality.services.complete_json', side_effect=incomplete) as complete:
            first = self.submit(row)
            process_job(first.pk)
            self.assertEqual(complete.call_count, 2)
            first.refresh_from_db()
            trace = self.client.get(f'/api/personality/assessments/{row.pk}/analysis').json()
            issue = trace['jobs'][0]['validation_errors'][0]
            self.assertEqual(issue['path'], 'match.similarities[0].user_evidence')
            self.assertEqual(issue['expected'], 'array')
            response = self.send(f'/api/personality/assessments/{row.pk}/submit')
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()['retry_block_reason'], 'cooldown')
            self.age(first)
            second = self.submit(row)
            process_job(second.pk)
            self.assertEqual(complete.call_count, 3)
            self.age(second)
            PersonalityJob.objects.filter(pk=second.pk).update(created_at='2000-01-01T00:00:00+00:00')
            blocked = self.send(f'/api/personality/assessments/{row.pk}/submit')
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked.json()['retry_block_reason'], 'assessment_budget')
        row.refresh_from_db()
        self.assertEqual(row.model_requests, 3)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).model_requests, 3)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 1)
        self.assertEqual(PersonalityJob.objects.filter(assessment=row, kind='report').count(), 2)
        state = self.client.get(f'/api/personality/assessments/{row.pk}/report').json()
        self.assertFalse(state['can_retry'])
        self.assertEqual(state['retry_block_reason'], 'assessment_budget')

    def test_timeout_is_not_refunded_and_polling_never_calls_model(self):
        row = self.prepare()
        with patch('apps.personality.services.complete_json', side_effect=AnalysisUnavailable('连接超时', retryable=True, reason='timeout')) as complete:
            job = self.submit(row)
            process_job(job.pk)
            for _ in range(5):
                response = self.client.get(f'/api/personality/assessments/{row.pk}/report')
                self.assertEqual(response.status_code, 200)
            self.assertEqual(complete.call_count, 1)
        row.refresh_from_db(); job.refresh_from_db()
        self.assertEqual(row.model_requests, 1)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).model_requests, 1)
        state = response.json()
        self.assertEqual(state['retry_block_reason'], 'cooldown')
        self.assertGreater(state['retry_after'], 0)
        self.age(job)
        state = self.client.get(f'/api/personality/assessments/{row.pk}/report').json()
        self.assertTrue(state['can_retry'])

    def test_interrupted_job_does_not_refund_reserved_request(self):
        row = self.prepare(); job = self.submit(row)
        usage, _ = DailyUsage.objects.get_or_create(user=self.alice, day=timezone.localdate().isoformat())
        Assessment.objects.filter(pk=row.pk).update(status='processing', model_requests=1)
        DailyUsage.objects.filter(pk=usage.pk).update(model_requests=1)
        PersonalityJob.objects.filter(pk=job.pk).update(status='processing', claim_token='interrupted', updated_at='2000-01-01T00:00:00+00:00')
        with patch('apps.personality.services.complete_json') as complete:
            recover_jobs()
            complete.assert_not_called()
        row.refresh_from_db(); job.refresh_from_db()
        self.assertEqual(row.status, 'failed')
        self.assertEqual(row.model_requests, 1)
        self.assertEqual(DailyUsage.objects.get(pk=usage.pk).model_requests, 1)
        self.assertEqual(job.parameters['failure_reason'], 'interrupted')

    def test_configuration_failure_does_not_reserve_or_offer_retry(self):
        row = self.prepare(); job = self.submit(row)
        PersonalitySettings.objects.filter(pk=1).update(ai_enabled=False)
        with patch('apps.personality.services.complete_json') as complete:
            process_job(job.pk)
            complete.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.model_requests, 0)
        self.assertFalse(DailyUsage.objects.filter(user=self.alice, model_requests__gt=0).exists())
        state = self.client.get(f'/api/personality/assessments/{row.pk}/report').json()
        self.assertFalse(state['can_retry'])
        self.assertEqual(state['retry_block_reason'], 'service_unavailable')

    def test_duplicate_submission_is_idempotent_and_get_is_read_only(self):
        row = self.prepare(); endpoint = f'/api/personality/assessments/{row.pk}/submit'
        self.assertEqual(self.send(endpoint).status_code, 202)
        self.assertEqual(self.send(endpoint).status_code, 200)
        self.assertEqual(PersonalityJob.objects.filter(assessment=row, kind='report').count(), 1)
        with patch('apps.personality.services.complete_json') as complete:
            for _ in range(4):
                self.assertEqual(self.client.get(f'/api/personality/assessments/{row.pk}/report').status_code, 200)
            complete.assert_not_called()

    def test_daily_model_budget_survives_log_cleanup_and_assessment_deletion(self):
        row = self.prepare()
        usage, _ = DailyUsage.objects.get_or_create(user=self.alice, day=timezone.localdate().isoformat())
        DailyUsage.objects.filter(pk=usage.pk).update(model_requests=15)
        job = self.submit(row)
        AnalysisCall.objects.create(assessment=row, job=job, stage='fixture')
        AnalysisCall.objects.all().delete()
        with patch('apps.personality.services.complete_json') as complete:
            process_job(job.pk)
            complete.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.model_requests, 0)
        self.assertEqual(DailyUsage.objects.get(pk=usage.pk).model_requests, 15)
        self.client.delete(f'/api/personality/assessments/{row.pk}')
        self.assertEqual(DailyUsage.objects.get(pk=usage.pk).model_requests, 15)

    def test_character_completion_cannot_bypass_assessment_budget(self):
        row = self.prepare()
        report = build_report(row); report['character'] = None
        row.report = report; row.status = 'completed'; row.model_requests = 3
        row.save(update_fields=['report', 'status', 'model_requests'])
        response = self.send(f'/api/personality/assessments/{row.pk}/complete-character')
        self.assertEqual(response.status_code, 429)
        self.assertFalse(PersonalityJob.objects.filter(assessment=row).exists())

    def cached_response(self, row):
        captured = {}
        def reply(settings, prompt, payload):
            captured['payload'] = copy.deepcopy(payload)
            result = self.combined(row, payload)
            for group in ('similarities', 'differences'):
                for item in result['match'][group]:
                    if isinstance(item['user_evidence'], list):
                        item['user_evidence'] = item['user_evidence'][0]
                    if isinstance(item['character_evidence'], list):
                        item['character_evidence'] = item['character_evidence'][0]
            captured['result'] = result
            return result
        saved = {}
        def save(phase, payload):
            saved.update(copy.deepcopy(payload))
        try:
            generate(row, build_report(row), config(), reply, eligible_characters(), save=save)
        except AnalysisUnavailable as exc:
            self.fail(f'{exc}: {saved.get("single_report", {}).get("validation_errors")}')
        job = PersonalityJob.objects.create(kind='report', assessment=row, status='failed', requested_by='fixture')
        call = AnalysisCall.objects.create(
            assessment=row, job=job, stage='personality_report:complete', status='returned',
            request={'messages': [{'role': 'system', 'content': 'fixture'}, {'role': 'user', 'content': json.dumps(captured['payload'], ensure_ascii=False)}]},
            response={'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(captured['result'], ensure_ascii=False)}}]},
            usage={})
        original_response = copy.deepcopy(call.response)
        original_answers = copy.deepcopy(row.answers)
        row.status = 'failed'; row.model_requests = 6
        row.save(update_fields=['status', 'model_requests'])
        usage, _ = DailyUsage.objects.get_or_create(user=self.alice, day=timezone.localdate().isoformat())
        DailyUsage.objects.filter(pk=usage.pk).update(model_requests=6)
        return job, call, original_response, original_answers

    def test_dry_run_and_explicit_apply_recover_paid_strings_without_ai(self):
        row = self.prepare(); job, call, original_response, original_answers = self.cached_response(row)
        before_reports = copy.deepcopy(row.report)
        source, _ = source_answers(row); source = compact_answers(source)
        packets, pool = anonymous_candidates(candidate_pool(build_report(row), eligible_characters(), str(row.pk)))
        state = {'sections': {}}
        self.assertEqual(row.analysis_calls.count(), 1)
        self.assertIsNotNone(returned_result(call))
        eligible_calls = AnalysisCall.objects.filter(assessment_id=row.pk, job__assessment_id=row.pk, job__kind='report', status='returned').exclude(Q(job__parameters__has_key='character_only') & Q(job__parameters__character_only=True)).exclude(Q(job__parameters__has_key='heartline_only') & Q(job__parameters__heartline_only=True))
        self.assertEqual(eligible_calls.count(), 1)
        replayed = replay_paid_results(row, json.loads(call.request['messages'][1]['content']), state, source, build_report(row), pool)
        self.assertTrue(replayed)
        output = io.StringIO()
        call_command('recover_personality_report', str(row.pk), stdout=output)
        self.assertIn('"recoverable": true', output.getvalue())
        self.assertIn('dry-run 完成', output.getvalue())
        row.refresh_from_db(); call.refresh_from_db()
        self.assertEqual(row.status, 'failed'); self.assertEqual(row.report, before_reports)
        self.assertEqual(call.response, original_response)
        with patch('apps.personality.services.complete_json') as complete:
            call_command('recover_personality_report', str(row.pk), '--apply', '--operator', 'test-admin', stdout=io.StringIO())
            complete.assert_not_called()
        row.refresh_from_db(); call.refresh_from_db()
        self.assertEqual(row.status, 'completed')
        self.assertEqual(row.report['character']['id'], self.role.pk)
        self.assertEqual(row.model_requests, 6)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).model_requests, 6)
        self.assertEqual(row.answers, original_answers)
        self.assertEqual(call.response, original_response)
        recovery = PersonalityJob.objects.get(assessment=row, parameters__recovery_only=True)
        self.assertEqual(recovery.requested_by, 'test-admin')
        self.assertTrue(recovery.result['recovered_calls'])

    def test_withdrawn_character_invalidates_cached_match(self):
        row = self.prepare(); self.cached_response(row)
        Character.objects.filter(pk=self.role.pk).update(status='excluded')
        with self.assertRaises(CommandError):
            call_command('recover_personality_report', str(row.pk), stdout=io.StringIO())
        row.refresh_from_db()
        self.assertEqual(row.status, 'failed')
        self.assertFalse(row.report)


class ConcurrentRequestBudgetTests(TransactionTestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username='personality_alice', password='test-only', created_at=timestamp())
        self.bob = User.objects.create_user(username='personality_bob', password='test-only', created_at=timestamp())
        fixtures.PersonalityTests.setUp(self)

    send = fixtures.PersonalityTests.send
    character = fixtures.PersonalityTests.character
    finish = fixtures.PersonalityTests.finish
    create = fixtures.PersonalityTests.create
    public_finish = SingleReportJourneyTests.public_finish
    prepare = SingleReportJourneyTests.prepare

    def test_multi_tab_submission_creates_only_one_job_and_one_report_allowance(self):
        row = self.prepare(); endpoint = f'/api/personality/assessments/{row.pk}/submit'
        clients = [Client() for _ in range(8)]
        for client in clients:
            client.force_login(self.alice)
        def submit(client):
            try:
                return client.post(endpoint, data='{}', content_type='application/json').status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(submit, clients))
        self.assertEqual(statuses.count(202), 1)
        self.assertEqual(statuses.count(200), 7)
        self.assertEqual(PersonalityJob.objects.filter(assessment=row, kind='report').count(), 1)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 1)

    def test_concurrent_atomic_reservation_stops_at_three_across_assessment_and_day(self):
        row = self.prepare(); settings = config()
        def reserve(_):
            try:
                reserve_report_request(row, settings)
                return 'reserved'
            except AnalysisUnavailable as exc:
                return exc.reason
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(reserve, range(8)))
        self.assertEqual(outcomes.count('reserved'), 3)
        self.assertEqual(outcomes.count('assessment_budget'), 5)
        row.refresh_from_db()
        self.assertEqual(row.model_requests, 3)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).model_requests, 3)
