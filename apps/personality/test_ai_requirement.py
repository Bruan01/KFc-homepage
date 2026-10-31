"""AI readiness, explicit consent and resumable failures at the public boundary."""
import copy
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from . import tests as fixtures
from .configuration import connection_fingerprint
from .models import Assessment, DailyUsage, PersonalityJob, PersonalitySettings
from .provider import AnalysisUnavailable
from .services import build_report, process_job


class RequiredAIWorkflowTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    create = fixtures.PersonalityTests.create
    finish = fixtures.PersonalityTests.finish

    def start(self, **body):
        return self.send('/api/personality/assessments', body)

    def test_unconfigured_start_is_blocked_without_creating_a_record(self):
        config = self.client.get('/api/personality/config')
        self.assertFalse(config.json()['ai_available'])
        self.assertTrue(config.json()['ai_required'])
        self.assertFalse(config.json()['can_start'])
        self.assertEqual(config['Cache-Control'], 'no-store')
        self.assertEqual(self.start(ai_consent=True).status_code, 503)
        self.assertFalse(Assessment.objects.exists())
        self.assertFalse(DailyUsage.objects.exists())

    def test_missing_key_disabled_failed_or_unchecked_connection_cannot_start(self):
        fixtures.ready_ai_fixture()
        for changes in [{'api_key_ciphertext': ''}, {'ai_enabled': False}, {'provider_check': {}},
                        {'model': 'changed-since-check'}, {'api_key_ciphertext': 'broken-ciphertext'}]:
            with self.subTest(changes=list(changes)):
                fixtures.ready_ai_fixture()
                PersonalitySettings.objects.filter(pk=1).update(**changes)
                self.assertFalse(self.client.get('/api/personality/config').json()['can_start'])
                self.assertEqual(self.start(ai_consent=True).status_code, 503)
        settings = fixtures.ready_ai_fixture()
        settings.refresh_from_db()
        PersonalitySettings.objects.filter(pk=1).update(provider_check={
            'status': 'failed', 'fingerprint': connection_fingerprint(settings)})
        self.assertEqual(self.start(ai_consent=True).status_code, 503)
        self.assertFalse(Assessment.objects.exists())

    def test_consent_is_required_and_ready_service_does_not_contact_model_on_start(self):
        fixtures.ready_ai_fixture()
        for consent in [False, 'true', None]:
            self.assertEqual(self.start(ai_consent=consent).status_code, 400)
        self.assertEqual(self.start().status_code, 400)
        with patch('apps.personality.provider._request') as upstream:
            response = self.start(ai_consent=True)
            self.assertEqual(response.status_code, 201)
            self.assertTrue(response.json()['ai_consent'])
            upstream.assert_not_called()

    def test_pausing_new_tests_does_not_delete_or_block_existing_answers(self):
        fixtures.ready_ai_fixture()
        state = self.start(ai_consent=True).json()
        PersonalitySettings.objects.filter(pk=1).update(enabled=False, ai_enabled=False)
        self.assertEqual(self.start(ai_consent=True).status_code, 503)
        key = state['step']['questions'][0]['id']
        response = self.send('/api/personality/assessments/'+state['id'], {
            'revision': state['revision'], 'answers': {key: {'value': 5, 'note': '以前会勉强，现在更愿意先休息。'}}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['answers'][key]['value'], 5)
        self.assertEqual(self.client.get('/api/personality/assessments/'+state['id']).json()['answers'], response.json()['answers'])

    def test_submit_outage_retains_ready_state_answers_and_quota(self):
        row = self.finish(consent=True)
        original = copy.deepcopy(row.answers)
        PersonalitySettings.objects.filter(pk=1).update(api_key_ciphertext='')
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/submit').status_code, 503)
        row.refresh_from_db()
        self.assertEqual(row.status, 'ready')
        self.assertEqual(row.answers, original)
        self.assertFalse(PersonalityJob.objects.filter(assessment=row).exists())
        self.assertFalse(DailyUsage.objects.filter(user=self.alice, reports__gt=0).exists())

    @patch('apps.personality.services.enrich_report')
    def test_runtime_failure_and_retry_reuse_checkpoint_and_one_report_allowance(self, enrich):
        row = self.finish(consent=True)
        PersonalitySettings.objects.filter(pk=1).update(daily_reports_per_user=1)
        original = copy.deepcopy(row.answers)
        def fail(owner, report, settings, checkpoint, save):
            save('person_analysis_inner', {'persona_parts': {'inner': ['validated-fixture']}})
            raise AnalysisUnavailable('连接暂时超时，回答已保存')
        enrich.side_effect = fail
        endpoint = f'/api/personality/assessments/{row.pk}/submit'
        self.assertEqual(self.send(endpoint).status_code, 202)
        first = PersonalityJob.objects.get(assessment=row)
        process_job(first.pk)
        row.refresh_from_db();first.refresh_from_db()
        self.assertEqual(row.status, 'failed')
        self.assertEqual(row.answers, original)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 1)
        # Retry remains possible after cooldown even when today's report allowance is fully reserved.
        PersonalityJob.objects.filter(pk=first.pk).update(updated_at='2000-01-01T00:00:00+00:00')
        self.assertEqual(self.send(endpoint).status_code, 202)
        retry = PersonalityJob.objects.get(assessment=row, status='queued')
        self.assertEqual(retry.checkpoint, first.checkpoint)
        enrich.side_effect = lambda owner, report, *args: {**report, 'analysis_mode': 'ai'}
        process_job(retry.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, 'completed')
        self.assertEqual(row.report['analysis_mode'], 'ai')
        self.assertEqual(row.answers, original)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 1)
        self.assertEqual(self.send(endpoint).status_code, 200)
        self.assertEqual(PersonalityJob.objects.filter(assessment=row).count(), 2)

    @patch('apps.personality.services.enrich_report')
    def test_queued_job_never_silently_downgrades_when_configuration_disappears(self, enrich):
        row = self.finish(consent=True)
        self.send(f'/api/personality/assessments/{row.pk}/submit')
        job = PersonalityJob.objects.get(assessment=row)
        PersonalitySettings.objects.filter(pk=1).update(ai_enabled=False)
        process_job(job.pk)
        row.refresh_from_db();job.refresh_from_db()
        self.assertEqual(row.status, 'failed')
        self.assertFalse(row.report)
        self.assertTrue(job.checkpoint == {})
        enrich.assert_not_called()

    @patch('apps.personality.services.enrich_report', side_effect=lambda row, report, *args: {**report, 'analysis_mode': 'ai'})
    def test_old_queued_false_flag_uses_ai_only_when_assessment_was_authorized(self, enrich):
        row = self.finish(consent=True)
        row.status = 'queued';row.save()
        job = PersonalityJob.objects.create(kind='report', assessment=row, requested_by=self.alice.username, parameters={'ai': False})
        process_job(job.pk)
        row.refresh_from_db();job.refresh_from_db()
        self.assertEqual(row.status, 'completed')
        self.assertTrue(job.parameters['ai'])
        enrich.assert_called_once()

    def test_legacy_record_can_authorize_without_reanswering_or_overwriting_answers(self):
        row = self.finish(consent=False)
        fixtures.ready_ai_fixture()
        original = copy.deepcopy(row.answers)
        response = self.send(f'/api/personality/assessments/{row.pk}', {
            'action': 'authorize_ai', 'ai_consent': True, 'revision': row.revision})
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertTrue(row.ai_consent)
        self.assertEqual(row.answers, original)
        self.assertEqual(row.status, 'ready')
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/submit').status_code, 202)

    @patch('apps.personality.services.enrich_report')
    def test_old_unauthorized_job_stops_and_explicit_retry_can_authorize(self, enrich):
        fixtures.ready_ai_fixture()
        row = self.finish(consent=False)
        row.status = 'queued';row.save()
        job = PersonalityJob.objects.create(kind='report', assessment=row, requested_by=self.alice.username, parameters={'ai': False})
        process_job(job.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, 'failed')
        enrich.assert_not_called()
        self.assertTrue(self.client.get(f'/api/personality/assessments/{row.pk}/report').json()['needs_ai_consent'])
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/submit').status_code, 400)
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/submit', {'ai_consent': True}).status_code, 202)
        row.refresh_from_db()
        self.assertTrue(row.ai_consent)

    def test_failed_optional_job_does_not_grant_a_free_first_report(self):
        row = self.finish(consent=True)
        PersonalityJob.objects.create(kind='report', assessment=row, status='failed', requested_by='root', parameters={'character_only': True})
        PersonalityJob.objects.create(kind='report', assessment=row, status='failed', requested_by='root', parameters={'heartline_only': True})
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/submit').status_code, 202)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 1)

    def test_already_completed_report_stays_unchanged_without_ai_service(self):
        row = self.finish();row.report = build_report(row);row.status = 'completed';row.save()
        original = copy.deepcopy(row.report)
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/submit').status_code, 200)
        self.assertEqual(self.client.get(f'/api/personality/assessments/{row.pk}/report').json()['report'], original)

    def test_retry_on_later_day_does_not_charge_a_second_report(self):
        row = self.finish(consent=True)
        row.status = 'failed';row.save()
        PersonalityJob.objects.create(kind='report', assessment=row, status='failed', requested_by='root',
            parameters={'ai': True, 'quota_reserved': True}, created_at='2026-01-01T10:00:00+00:00')
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/submit').status_code, 202)
        self.assertFalse(DailyUsage.objects.filter(user=self.alice, day=timezone.localdate().isoformat(), reports__gt=0).exists())
