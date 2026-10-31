import copy
from datetime import timedelta
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TestCase
from django.utils import timezone

from apps.notifications.models import Notification
from . import tests as fixtures
from .models import Assessment, OperationalAlert, PersonalityJob, PersonalitySettings, QuestionFeedback, timestamp
from .operations import delayed, flag_job, readiness, scan_alerts
from .services import process_job


class OperationsTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    create = fixtures.PersonalityTests.create
    finish = fixtures.PersonalityTests.finish
    character = fixtures.PersonalityTests.character

    def admin_data(self):
        return self.admin.get('/api/admin/personality/operations').json()

    def make_job(self, *, status='queued', minutes=5):
        row = self.finish(consent=True)
        row.status = status;row.save()
        job = PersonalityJob.objects.create(kind='report', assessment=row, status=status, parameters={'ai': True},
            requested_by=self.alice.username, updated_at=(timezone.now()-timedelta(minutes=minutes)).isoformat())
        return row, job

    def test_readiness_checks_saved_ai_worker_and_complete_role_independently(self):
        settings = fixtures.ready_ai_fixture()
        self.assertFalse(readiness(settings)['ready'])
        settings.worker_last_seen_at = timestamp();settings.save()
        role = self.character()
        self.assertTrue(readiness(settings)['ready'])
        role.profile = {};role.save()
        data = readiness(settings)
        self.assertFalse(data['ready'])
        self.assertFalse(next(check['ready'] for check in data['checks'] if check['key'] == 'characters'))
        settings.enabled = False
        self.assertFalse(next(check['ready'] for check in readiness(settings)['checks'] if check['key'] == 'enabled'))

    def test_operations_and_actions_are_super_admin_only_and_private(self):
        self.assertEqual(Client().get('/api/admin/personality/operations').status_code, 401)
        self.assertEqual(self.client.get('/api/admin/personality/operations').status_code, 401)
        restricted = Client();session = restricted.session
        session['admin_username'] = 'moderator';session['admin_level'] = 3;session['admin_is_super'] = False;session.save()
        self.assertEqual(restricted.get('/api/admin/personality/operations').status_code, 403)
        self.assertEqual(restricted.get('/admin/personality/operations').status_code, 403)
        placeholder = '11111111-1111-4111-8111-111111111111'
        self.assertEqual(self.send(f'/api/admin/personality/operations/alerts/{placeholder}/acknowledge', client=restricted).status_code, 403)
        self.assertEqual(self.send(f'/api/admin/personality/operations/feedback/{placeholder}/handle', client=restricted).status_code, 403)
        response = self.admin.get('/api/admin/personality/operations?summary=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(set(response.json()), {'readiness', 'counts'})
        self.assertEqual(self.admin.get('/admin/personality/operations').status_code, 200)

    def test_feedback_is_owner_only_idempotent_and_never_contains_answers(self):
        state = self.create();row = Assessment.objects.get(pk=state['id']);key = row.steps[0]['questions'][0]['id']
        row.answers = {key: {'value': 5, 'note': 'PRIVATE_ANSWER_NEVER_IN_FEEDBACK'}};row.save()
        original = copy.deepcopy(row.answers)
        endpoint = f'/api/personality/assessments/{row.pk}/question-feedback'
        self.assertEqual(self.send(endpoint, {'question_id': key}).status_code, 201)
        self.assertEqual(self.send(endpoint, {'question_id': key}).status_code, 200)
        self.assertEqual(QuestionFeedback.objects.count(), 1)
        self.assertIn(key, self.client.get(f'/api/personality/assessments/{row.pk}').json()['feedback_question_ids'])
        self.assertEqual(self.send(endpoint, {'question_id': 'made-up'}).status_code, 400)
        self.assertEqual(self.send(endpoint, {'question_id': []}).status_code, 400)
        other = Client();other.force_login(self.bob)
        self.assertEqual(self.send(endpoint, {'question_id': key}, client=other).status_code, 404)
        strict = Client(enforce_csrf_checks=True);strict.force_login(self.alice)
        self.assertEqual(self.send(endpoint, {'question_id': key}, client=strict).status_code, 403)
        row.refresh_from_db();self.assertEqual(row.answers, original)
        data = self.admin.get('/api/admin/personality/operations').content.decode()
        self.assertNotIn('PRIVATE_ANSWER_NEVER_IN_FEEDBACK', data)
        self.assertNotIn(self.alice.username, data)

    def test_feedback_groups_same_wording_but_not_different_versions_or_dynamic_text(self):
        row = Assessment.objects.create(user=self.alice)
        other = Assessment.objects.create(user=self.bob)
        one = QuestionFeedback.objects.create(assessment=row, question_id='same-id', question_version='v1', question_text='这是一道测试题。')
        QuestionFeedback.objects.create(assessment=other, question_id='same-id', question_version='v1', question_text='这是一道测试题。')
        QuestionFeedback.objects.create(assessment=row, question_id='different-id', question_version='v2', question_text='另一道测试题。')
        groups = self.admin_data()['feedback']
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['pending'], 2)
        self.assertEqual(self.send(f'/api/admin/personality/operations/feedback/{one.pk}/handle', client=self.admin).status_code, 200)
        self.assertEqual(len(self.admin_data()['feedback']), 1)
        self.assertEqual(QuestionFeedback.objects.filter(status='handled').count(), 2)
        self.assertEqual(QuestionFeedback.objects.get(pk=one.pk).handled_by, 'root')

    def test_old_question_does_not_copy_embedded_private_quote_to_feedback(self):
        row = Assessment.objects.create(user=self.alice, steps=[{'questions':[{
            'id':'follow-context', 'kind':'open', 'text':'你说过 PRIVATE_QUOTE，请讲讲原因。'}]}])
        self.send(f'/api/personality/assessments/{row.pk}/question-feedback', {'question_id':'follow-context'})
        self.assertNotIn('PRIVATE_QUOTE', QuestionFeedback.objects.get().question_text)

    @patch('apps.personality.services.complete_json')
    def test_waiting_report_shows_saved_notice_and_records_one_admin_alert(self, complete):
        row, job = self.make_job()
        original = copy.deepcopy(row.answers)
        endpoint = f'/api/personality/assessments/{row.pk}/report'
        for _ in range(3):
            data = self.client.get(endpoint).json()
            self.assertTrue(data['is_delayed'])
            self.assertTrue(data['reported_to_admin'])
            self.assertIn('回答已保存，不用重做', data['notice'])
        self.assertEqual(OperationalAlert.objects.count(), 1)
        complete.assert_not_called()
        job.refresh_from_db();row.refresh_from_db()
        self.assertEqual(job.status, 'queued');self.assertEqual(row.answers, original)

    def test_admin_can_detect_stopped_worker_without_user_polling(self):
        row, job = self.make_job()
        self.assertEqual(OperationalAlert.objects.count(), 0)
        data = self.admin_data()
        self.assertEqual(data['counts']['alerts'], 1)
        self.assertEqual(data['alerts'][0]['assessment_id'], str(row.pk))
        self.assertFalse(next(check['ready'] for check in data['readiness']['checks'] if check['key'] == 'worker'))

    def test_recent_phase_progress_is_not_stale_and_provider_retry_has_time_to_finish(self):
        row, job = self.make_job(status='processing', minutes=1)
        settings = PersonalitySettings.objects.get(pk=1);settings.timeout_seconds = 180
        job.updated_at = (timezone.now()-timedelta(seconds=350)).isoformat()
        self.assertFalse(delayed(job, settings))
        job.updated_at = (timezone.now()-timedelta(seconds=430)).isoformat()
        self.assertTrue(delayed(job, settings))
        job.updated_at = timestamp();job.save()
        scan_alerts(settings)
        self.assertFalse(OperationalAlert.objects.exists())

    def test_acknowledging_does_not_cancel_job_and_recovery_resolves_alert(self):
        row, job = self.make_job()
        self.admin_data();alert = OperationalAlert.objects.get()
        self.assertEqual(self.send(f'/api/admin/personality/operations/alerts/{alert.pk}/acknowledge', client=self.admin).status_code, 200)
        data = self.admin_data()
        self.assertEqual(data['counts']['alerts'], 0)
        self.assertEqual(data['alerts'][0]['status'], 'acknowledged')
        job.refresh_from_db();self.assertEqual(job.status, 'queued')
        job.updated_at = timestamp();job.save();self.admin_data();alert.refresh_from_db()
        self.assertEqual(alert.status, 'resolved')
        job.updated_at = (timezone.now()-timedelta(minutes=5)).isoformat();job.save();self.admin_data();alert.refresh_from_db()
        self.assertEqual(alert.status, 'open')

    @patch('apps.personality.services.enrich_report', side_effect=ValueError('INTERNAL_DETAIL_DO_NOT_SHOW'))
    def test_failure_alert_is_recorded_but_user_does_not_receive_internal_error(self, enrich):
        row, job = self.make_job(minutes=0)
        process_job(job.pk)
        self.assertEqual(OperationalAlert.objects.get(job=job).code, 'failed')
        data = self.client.get(f'/api/personality/assessments/{row.pk}/report').json()
        self.assertIn('回答已保存', data['error'])
        self.assertEqual(data['retry_block_reason'], 'cooldown')
        self.assertNotIn('INTERNAL_DETAIL', data['error'])
        self.assertEqual(PersonalityJob.objects.get(pk=job.pk).error, 'INTERNAL_DETAIL_DO_NOT_SHOW')

    @patch('apps.personality.services.enrich_report', side_effect=lambda row, report, *args: {**report, 'analysis_mode':'ai'})
    def test_report_completion_notifies_owner_once_and_resolves_stale_alert(self, enrich):
        row, job = self.make_job()
        flag_job(job, 'stalled')
        process_job(job.pk);process_job(job.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, 'completed')
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient_id, self.alice.pk)
        self.assertEqual(notification.type, 'system')
        self.assertEqual(notification.link, f'/personality/report/{row.pk}')
        self.assertNotIn('你的回答', notification.body)
        feed = self.client.get('/api/notifications?category=system').json()
        self.assertEqual(feed['items'][0]['link'], notification.link)
        other = Client();other.force_login(self.bob)
        self.assertEqual(other.get('/api/notifications?category=system').json()['items'], [])
        self.assertEqual(OperationalAlert.objects.get(job=job).status, 'resolved')
        self.assertEqual(self.admin_data()['counts']['alerts'], 0)

    @patch('apps.personality.services.enrich_report', side_effect=lambda row, report, *args: {**report, 'analysis_mode':'ai'})
    @patch('apps.notifications.models.Notification.objects.get_or_create', side_effect=DatabaseError('temporary'))
    def test_notification_storage_failure_does_not_lose_completed_report(self, notify, enrich):
        row, job = self.make_job(minutes=0)
        process_job(job.pk);row.refresh_from_db()
        self.assertEqual(row.status, 'completed')
        self.assertEqual(row.report['analysis_mode'], 'ai')
        job.refresh_from_db()
        self.assertTrue(job.result['notification_pending'])

    @patch('apps.personality.services.enrich_report', side_effect=lambda row, report, *args: {**report, 'analysis_mode':'ai'})
    def test_pending_completion_notification_is_retried_without_duplicate_or_model_call(self, enrich):
        row, job = self.make_job(minutes=0)
        with patch('apps.notifications.models.Notification.objects.get_or_create', side_effect=DatabaseError('temporary')):
            process_job(job.pk)
        self.assertFalse(Notification.objects.exists())
        scan_alerts(PersonalitySettings.objects.get(pk=1));scan_alerts(PersonalitySettings.objects.get(pk=1))
        self.assertEqual(Notification.objects.count(), 1)
        job.refresh_from_db();self.assertFalse(job.result['notification_pending'])
        self.assertEqual(enrich.call_count, 1)

    def test_retry_resolves_previous_alert_and_notifies_only_after_completion(self):
        row, job = self.make_job(status='failed')
        self.admin_data();self.assertEqual(OperationalAlert.objects.count(), 1)
        response = self.send(f'/api/personality/assessments/{row.pk}/submit')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(OperationalAlert.objects.get(job=job).status, 'resolved')
        self.assertFalse(Notification.objects.exists())

    def test_deleting_assessment_clears_feedback_alert_and_notification_link(self):
        row, job = self.make_job()
        flag_job(job, 'stalled')
        QuestionFeedback.objects.create(assessment=row, question_id='fixture', question_version='v1', question_text='测试题')
        notice = Notification.objects.create(recipient=self.alice, title='你的人格共鸣档案已生成', link=f'/personality/report/{row.pk}')
        self.client.delete(f'/api/personality/assessments/{row.pk}')
        self.assertFalse(OperationalAlert.objects.exists())
        self.assertFalse(QuestionFeedback.objects.exists())
        notice.refresh_from_db();self.assertEqual(notice.link, '')
