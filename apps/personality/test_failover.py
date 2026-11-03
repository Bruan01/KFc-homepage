import copy
import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

from django.test import Client, TestCase

from . import tests as fixtures
from .configuration import ai_service_status, backup_ready, remember_connection_check
from .models import AnalysisCall, DailyUsage, PersonalitySettings
from .provider import AnalysisUnavailable, complete_json, decrypt_key, encrypt_key
from .services import process_job
from .test_single_report import SingleReportJourneyTests


def response(content):
    reply = MagicMock()
    reply.__enter__.return_value.read.return_value = json.dumps({
        'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}]
    }).encode()
    return reply


def http_error(code, detail=None):
    return urllib.error.HTTPError('https://primary.invalid/v1', code, 'private error body', {},
        io.BytesIO(json.dumps({'error': detail or {}}).encode()))


class FailoverTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    character = fixtures.PersonalityTests.character
    finish = fixtures.PersonalityTests.finish
    create = fixtures.PersonalityTests.create
    public_finish = SingleReportJourneyTests.public_finish
    combined = SingleReportJourneyTests.combined
    prepare = SingleReportJourneyTests.prepare
    submit = SingleReportJourneyTests.submit

    def ready_backup(self):
        settings = fixtures.ready_ai_fixture()
        settings.base_url = 'https://primary.invalid/v1'
        settings.model = 'primary-model'
        settings.api_key_ciphertext = encrypt_key('primary-test-secret')
        settings.backup_enabled = True
        settings.backup_base_url = 'https://backup.invalid/v1'
        settings.backup_model = 'backup-model'
        settings.backup_api_key_ciphertext = encrypt_key('backup-test-secret')
        settings.save()
        remember_connection_check(settings, 'passed')
        remember_connection_check(settings, 'passed', backup=True)
        settings.refresh_from_db()
        return settings

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_primary_success_does_not_contact_backup(self, opener):
        settings = self.ready_backup()
        opener.return_value.open.return_value = response({'ok': True})
        self.assertEqual(complete_json(settings, 'test', {}), {'ok': True})
        opener.return_value.open.assert_called_once()
        self.assertEqual(opener.return_value.open.call_args.args[0].full_url, settings.base_url+'/chat/completions')

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_outage_balance_auth_rate_limit_and_timeout_switch_once_with_independent_key(self, opener):
        settings = self.ready_backup()
        failures = [http_error(code) for code in (401, 402, 403, 404, 429, 500, 503)]
        failures += [TimeoutError(), urllib.error.URLError('unavailable'), http_error(400, {'code':'insufficient_quota'})]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__, code=getattr(failure, 'code', None)):
                opener.reset_mock()
                opener.return_value.open.side_effect = [failure, response({'ok': True})]
                self.assertEqual(complete_json(settings, 'test', {}), {'ok': True})
                self.assertEqual(opener.return_value.open.call_count, 2)
                primary, backup = [item.args[0] for item in opener.return_value.open.call_args_list]
                self.assertEqual(primary.get_header('Authorization'), 'Bearer primary-test-secret')
                self.assertEqual(backup.get_header('Authorization'), 'Bearer backup-test-secret')
                self.assertEqual(backup.full_url, 'https://backup.invalid/v1/chat/completions')
                body = json.loads(backup.data)
                self.assertEqual(body['model'], 'backup-model')
                self.assertNotIn('_provider', body)
                self.assertEqual(body['messages'], json.loads(primary.data)['messages'])

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_both_services_fail_stop_after_two_requests_without_exposing_body(self, opener):
        settings = self.ready_backup()
        opener.return_value.open.side_effect = [http_error(503), http_error(402, {'message':'secret'})]
        with self.assertRaises(AnalysisUnavailable) as caught:
            complete_json(settings, 'test', {})
        self.assertEqual(caught.exception.reason, 'insufficient_balance')
        self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(opener.return_value.open.call_count, 2)

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_bad_parameters_and_truncated_output_do_not_switch_services(self, opener):
        settings = self.ready_backup()
        for failure in [http_error(400, {'param':'max_tokens'}), http_error(422)]:
            opener.reset_mock(); opener.return_value.open.side_effect = failure
            with self.assertRaises(AnalysisUnavailable):
                complete_json(settings, 'test', {})
            opener.return_value.open.assert_called_once()
        opener.reset_mock(); opener.return_value.open.side_effect = None
        reply = response({})
        reply.__enter__.return_value.read.return_value = b'{"choices":[{"finish_reason":"length","message":{"content":"{}"}}]}'
        opener.return_value.open.return_value = reply
        with self.assertRaises(AnalysisUnavailable) as caught:
            complete_json(settings, 'test', {})
        self.assertEqual(caught.exception.reason, 'truncated')
        opener.return_value.open.assert_called_once()

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_disabled_unchecked_changed_or_undecryptable_backup_is_never_used(self, opener):
        settings = self.ready_backup()
        for changes in ({'backup_enabled':False}, {'backup_provider_check':{}},
                        {'backup_model':'changed'}, {'backup_api_key_ciphertext':'broken'}):
            current = copy.copy(settings)
            for key, value in changes.items():
                setattr(current, key, value)
            self.assertFalse(backup_ready(current))
            opener.reset_mock(); opener.return_value.open.side_effect = http_error(503)
            with self.assertRaises(AnalysisUnavailable):
                complete_json(current, 'test', {})
            opener.return_value.open.assert_called_once()

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_checked_backup_can_serve_when_primary_check_fails_but_global_off_still_blocks(self, opener):
        settings = self.ready_backup()
        settings.provider_check = {'status':'failed'}
        settings.save(update_fields=['provider_check'])
        self.assertTrue(ai_service_status(settings)[0])
        self.assertTrue(self.client.get('/api/personality/config').json()['can_start'])
        opener.return_value.open.return_value = response({'ok':True})
        complete_json(settings, 'test', {})
        opener.return_value.open.assert_called_once()
        self.assertIn('backup.invalid', opener.return_value.open.call_args.args[0].full_url)
        settings.ai_enabled = False
        self.assertFalse(ai_service_status(settings)[0])
        with self.assertRaises(AnalysisUnavailable):
            complete_json(settings, 'test', {})

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_worker_failover_counts_both_requests_preserves_report_cap_and_logs_provider(self, opener):
        row = self.prepare(); settings = self.ready_backup(); job = self.submit(row)
        original_answers = copy.deepcopy(row.answers)
        def upstream(request, **kwargs):
            body = json.loads(request.data)
            self.assertLessEqual(body['max_tokens'], 6000)
            if body['model'] == 'primary-model':
                raise http_error(402)
            return response(self.combined(row, json.loads(body['messages'][1]['content'])))
        opener.return_value.open.side_effect = upstream
        process_job(job.pk)
        row.refresh_from_db(); job.refresh_from_db()
        self.assertEqual(job.status, 'completed', job.error)
        self.assertEqual(row.status, 'completed')
        self.assertEqual(row.answers, original_answers)
        self.assertEqual(row.model_requests, 2)
        usage = DailyUsage.objects.get(user=row.user)
        self.assertEqual(usage.model_requests, 2); self.assertEqual(usage.reports, 1)
        calls = list(AnalysisCall.objects.filter(job=job))
        self.assertEqual([c.request['_provider']['slot'] for c in calls], ['primary', 'backup'])
        self.assertEqual([c.status for c in calls], ['error', 'returned'])
        self.assertNotIn('test-secret', json.dumps([c.request for c in calls]))

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_backup_does_not_bypass_user_request_budget(self, opener):
        row = self.prepare(); self.ready_backup()
        PersonalitySettings.objects.filter(pk=1).update(report_requests_per_assessment=1)
        job = self.submit(row)
        opener.return_value.open.side_effect = http_error(503)
        process_job(job.pk)
        row.refresh_from_db(); job.refresh_from_db()
        self.assertEqual(row.status, 'failed'); self.assertEqual(row.model_requests, 1)
        self.assertEqual(job.parameters['failure_reason'], 'assessment_budget')
        opener.return_value.open.assert_called_once()

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_primary_check_never_silently_passes_via_backup(self, opener):
        self.ready_backup()
        opener.return_value.open.side_effect = http_error(503)
        result = self.send('/api/admin/personality/test', {}, self.admin)
        self.assertEqual(result.status_code, 400)
        opener.return_value.open.assert_called_once()
        settings = PersonalitySettings.objects.get(pk=1)
        self.assertEqual(settings.provider_check['status'], 'failed')
        self.assertTrue(backup_ready(settings)); self.assertTrue(ai_service_status(settings)[0])

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_backup_check_is_independent_and_unsaved_check_cannot_certify_saved_model(self, opener):
        settings = self.ready_backup()
        old_check = copy.deepcopy(settings.backup_provider_check)
        opener.return_value.open.return_value = response({'ok':True})
        result = self.send('/api/admin/personality/test-backup', {'backup_model':'unsaved-model'}, self.admin)
        self.assertEqual(result.status_code, 200)
        settings.refresh_from_db(); self.assertEqual(settings.backup_provider_check, old_check)
        request = opener.return_value.open.call_args.args[0]
        self.assertIn('backup.invalid', request.full_url)
        self.assertEqual(json.loads(request.data)['model'], 'unsaved-model')
        opener.reset_mock()
        self.assertEqual(self.send('/api/admin/personality/test-backup', {}, self.admin).status_code, 200)
        opener.return_value.open.assert_called_once()

    def test_backup_config_encrypted_validated_private_and_independent_of_primary(self):
        settings = self.ready_backup()
        primary_check = copy.deepcopy(settings.provider_check)
        endpoint = '/api/admin/personality/settings'
        result = self.send(endpoint, {'backup_api_key':'replacement-secret'}, self.admin)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertNotIn('replacement-secret', result.content.decode())
        self.assertNotIn('backup_api_key_ciphertext', result.json()['settings'])
        settings.refresh_from_db()
        self.assertEqual(decrypt_key(settings.backup_api_key_ciphertext), 'replacement-secret')
        self.assertEqual(settings.provider_check, primary_check)
        self.assertFalse(backup_ready(settings))
        self.assertEqual(result.json()['settings']['backup_connection_check']['status'], 'unchecked')
        for body in ({'backup_enabled':'true'}, {'backup_timeout_seconds':0}, {'backup_max_output_tokens':32001},
                     {'backup_api_key':'a','clear_backup_api_key':True}, {'backup_token_parameter':'invalid'},
                     {'backup_base_url':'https://user:password@example.invalid/v1'}, {'backup_api_key':'a\nb'}):
            self.assertEqual(self.send(endpoint, body, self.admin).status_code, 400, body)
        self.assertEqual(self.send(endpoint, {'backup_api_key':''}, self.admin).status_code, 200)
        settings.refresh_from_db(); self.assertEqual(decrypt_key(settings.backup_api_key_ciphertext), 'replacement-secret')

    def test_backup_checks_and_config_are_super_admin_only_and_cannot_forge_check_results(self):
        settings = self.ready_backup()
        endpoint = '/api/admin/personality/test-backup'
        self.assertEqual(self.send(endpoint).status_code, 401)
        restricted = Client(); session = restricted.session
        session['admin_username']='moderator'; session['admin_level']=3; session['admin_is_super']=False; session.save()
        self.assertEqual(self.send(endpoint, {}, restricted).status_code, 403)
        self.assertEqual(self.send('/api/admin/personality/settings', {'backup_enabled':False}, restricted).status_code, 403)
        previous = settings.backup_api_key_ciphertext
        result = self.send('/api/admin/personality/settings', {'backup_api_key_ciphertext':'forged', 'backup_provider_check':{'status':'passed'}}, self.admin)
        self.assertEqual(result.status_code, 200)
        settings.refresh_from_db()
        self.assertEqual(settings.backup_api_key_ciphertext, previous)
        self.assertIn('fingerprint', settings.backup_provider_check)
