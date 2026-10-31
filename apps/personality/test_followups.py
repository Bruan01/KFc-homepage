"""Workflow checks for optional interview turns; not a model evaluation dataset."""
import copy
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from . import tests as fixtures
from .followups import source_payload
from .models import Assessment, DailyUsage, PersonalityJob, PersonalitySettings
from .provider import AnalysisUnavailable, complete_json
from .questions import quantified
from .services import process_job, recover_jobs


class FollowupWorkflowTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    create = fixtures.PersonalityTests.create
    NOTE = '我会答应朋友，但是回家之后会担心自己没有留出休息的时间。'

    def core(self, consent=True, legacy=False):
        PersonalitySettings.objects.update_or_create(pk=1, defaults={'ai_enabled': True, 'base_url': 'https://example.invalid/v1', 'model': 'fixture'})
        fixtures.ready_ai_fixture()
        state = self.create(ai_consent=consent)
        if legacy:
            row = Assessment.objects.get(pk=state['id']); row.steps[0].pop('followup_policy'); row.save(update_fields=['steps'])
        while state['status'] == 'active' and state['step_index'] < 8:
            state = self.answer(state)
        return state

    def answer(self, state, note=None, skipped=False):
        answers = {q['id']: {'value': 6 if q['kind'] == 'scale' else None, 'note': (note or self.NOTE) if q['kind'] == 'open' else '', 'skipped': skipped} for q in state['step']['questions']}
        response = self.send('/api/personality/assessments/'+state['id'], {'revision': state['revision'], 'answers': answers, 'complete': True})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def latest(self, state):
        return self.client.get('/api/personality/assessments/'+state['id']).json()

    def job(self, state):
        return PersonalityJob.objects.get(assessment_id=state['id'], kind='followup', status='queued')

    def result(self, payload):
        key = next(iter(payload['answers']))
        return {'done': False, 'source_question_id': key, 'source_quote': payload['answers'][key]['note'][:40], 'focus': 'boundary',
                'options': ['我需要留一点时间休息', '我担心朋友觉得自己被忽略', '我想把见面和休息的时间先商量好'],
                'question': '最近一次答应朋友时，你当时最在意的是什么？' if payload['batch'] == 'round_1' else '如果这次可以重新安排，你最想为自己保留什么？'}

    @patch('apps.personality.services.complete_json')
    def test_two_turns_use_fresh_reply_and_preserve_scores_and_refresh(self, complete):
        state = self.core(); self.assertEqual(state['step']['ai_followup']['state'], 'pending')
        row = Assessment.objects.get(pk=state['id']); before = quantified(row.steps, row.answers)
        payloads = []
        def respond(settings, prompt, payload):
            self.assertEqual(settings.timeout_seconds, 20); self.assertEqual(settings.max_output_tokens, 1200)
            payloads.append(copy.deepcopy(payload)); return self.result(payload)
        complete.side_effect = respond
        process_job(self.job(state).pk); state = self.latest(state)
        self.assertEqual(len(state['step']['questions']), 1)
        self.assertEqual(self.latest(state)['step'], state['step'])
        first = copy.deepcopy(state['step']); reply = '我是真的想见他们，但我希望先讲好自己回家的时间。'
        state = self.answer(state, reply); process_job(self.job(state).pk); state = self.latest(state)
        self.assertEqual(payloads[1]['previous_followups'][0]['answer'], reply)
        self.assertIn('ai-follow-1', payloads[1]['answers'])
        self.assertNotEqual(first['questions'][0]['text'], state['step']['questions'][0]['text'])
        state = self.answer(state); self.assertEqual(state['status'], 'ready')
        row.refresh_from_db(); self.assertEqual(quantified(row.steps, row.answers), before)
        self.assertEqual(complete.call_count, 2); self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 0)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).followup_requests, 2)
        self.assertEqual(PersonalityJob.objects.filter(assessment=row, kind='followup').count(), 2)

    def test_no_consent_and_legacy_assessments_use_original_questions(self):
        for kwargs in [{'consent': False}, {'legacy': True}]:
            state = self.core(**kwargs)
            self.assertNotIn('ai_followup', state['step'])
            self.assertFalse(PersonalityJob.objects.filter(assessment_id=state['id']).exists())
        state = self.core(); PersonalitySettings.objects.filter(pk=1).update(ai_enabled=False)
        with patch('apps.personality.services.complete_json') as complete:
            process_job(self.job(state).pk); complete.assert_not_called()
        self.assertEqual(self.latest(state)['step']['ai_followup']['state'], 'unavailable')

    @patch('apps.personality.services.complete_json', side_effect=AnalysisUnavailable('连接超时'))
    def test_timeout_keeps_interview_position_and_does_not_charge_report(self, complete):
        state = self.core(); job = self.job(state); process_job(job.pk); state = self.latest(state)
        self.assertEqual(state['step']['ai_followup']['state'], 'unavailable')
        self.assertEqual(state['step_index'], 8)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 0); job.refresh_from_db(); self.assertEqual(job.status, 'failed')

    @patch('apps.personality.services.complete_json')
    def test_paused_interview_retries_same_turn_without_losing_answers(self, complete):
        state = self.core(); original = copy.deepcopy(state['answers']); job = self.job(state)
        complete.side_effect = AnalysisUnavailable('连接超时')
        process_job(job.pk); state = self.latest(state)
        endpoint = '/api/personality/assessments/'+state['id']
        body = {'action': 'retry_followup', 'revision': state['revision']}
        PersonalitySettings.objects.filter(pk=1).update(ai_enabled=False)
        self.assertEqual(self.send(endpoint, body).status_code, 503)
        self.assertEqual(self.latest(state)['answers'], original)
        fixtures.ready_ai_fixture()
        response = self.send(endpoint, body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['step']['ai_followup']['state'], 'pending')
        self.assertEqual(PersonalityJob.objects.filter(assessment_id=state['id']).count(), 1)
        self.assertEqual(self.send(endpoint, body).status_code, 409)
        complete.side_effect = lambda settings, prompt, payload: self.result(payload)
        process_job(job.pk);state = self.latest(state)
        self.assertEqual(state['step']['ai_followup']['state'], 'generated')
        self.assertEqual(state['answers'], original)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).followup_requests, 1)

    @patch('apps.personality.services.complete_json', side_effect=AnalysisUnavailable('连接超时'))
    def test_paused_interview_can_be_skipped_without_clearing_answers(self, complete):
        state = self.core(); original = copy.deepcopy(state['answers']); process_job(self.job(state).pk);state = self.latest(state)
        response = self.send('/api/personality/assessments/'+state['id'], {'action': 'skip_followup', 'revision': state['revision']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ready')
        self.assertEqual(response.json()['answers'], original)

    @patch('apps.personality.services.complete_json', side_effect=RuntimeError('internal-only'))
    def test_unexpected_interview_error_does_not_leave_an_endless_pending_step(self, complete):
        state = self.core(); original = copy.deepcopy(state['answers']); job = self.job(state)
        process_job(job.pk); state = self.latest(state); job.refresh_from_db()
        self.assertEqual(state['step']['ai_followup']['state'], 'unavailable')
        self.assertEqual(state['answers'], original)
        self.assertEqual(job.status, 'failed')
        self.assertNotIn('internal-only', job.error)

    @patch('apps.personality.services.complete_json')
    def test_forged_quote_or_anime_question_cannot_reach_user(self, complete):
        for invalid in [{'source_quote': '这不是用户说过的任何一段话。'}, {'question': '你最喜欢哪个动漫角色，觉得自己与谁比较像？'}, {'focus': ['boundary']}, {'done': 'false'}, {'question': '你当时最在意什么？你为什么没有拒绝呢？'}]:
            state = self.core()
            complete.side_effect = lambda settings, prompt, payload: {**self.result(payload), **invalid}
            process_job(self.job(state).pk)
            self.assertEqual(self.latest(state)['step']['ai_followup']['state'], 'fallback')

    @patch('apps.personality.services.complete_json', return_value={'done': True})
    def test_sufficient_information_can_end_without_forced_question(self, complete):
        state = self.core(); process_job(self.job(state).pk)
        self.assertEqual(self.latest(state)['status'], 'ready'); self.assertEqual(complete.call_count, 1)
        state = self.latest(state)
        response = self.send('/api/personality/assessments/'+state['id'], {'revision': state['revision'], 'action': 'back'})
        self.assertEqual(response.json()['step_index'], 7)
        self.assertTrue(response.json()['step']['questions'])

    @patch('apps.personality.services.complete_json')
    def test_skipping_first_question_does_not_request_a_second(self, complete):
        state = self.core(); complete.side_effect = lambda settings, prompt, payload: self.result(payload)
        process_job(self.job(state).pk); state = self.answer(self.latest(state), skipped=True)
        self.assertEqual(state['status'], 'ready'); self.assertEqual(complete.call_count, 1)
        self.assertEqual(PersonalityJob.objects.filter(assessment_id=state['id'], kind='followup').count(), 1)

    @patch('apps.personality.services.complete_json')
    def test_skip_during_request_cancels_stale_result(self, complete):
        state = self.core(); job = self.job(state)
        def reply(settings, prompt, payload):
            response = self.send('/api/personality/assessments/'+state['id'], {'revision': state['revision'], 'action': 'skip_followup'})
            self.assertEqual(response.status_code, 200); self.assertEqual(response.json()['status'], 'ready')
            return self.result(payload)
        complete.side_effect = reply; process_job(job.pk); job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled'); self.assertEqual(self.latest(state)['status'], 'ready')
        self.assertEqual(self.latest(state)['step'], None)

    @patch('apps.personality.services.complete_json')
    def test_back_edit_removes_dependent_questions_and_never_queues_a_third_call(self, complete):
        state = self.core(); complete.side_effect = lambda settings, prompt, payload: self.result(payload)
        process_job(self.job(state).pk); first = self.latest(state)
        state = self.answer(first); second = self.job(state)
        state = self.send('/api/personality/assessments/'+state['id'], {'revision': state['revision'], 'action': 'back'}).json()
        state = self.answer(state, '这次我其实想拒绝，只是担心对方误解我不在乎这段关系。')
        second.refresh_from_db(); self.assertEqual(second.status, 'cancelled')
        self.assertEqual(state['step']['ai_followup']['state'], 'fallback')
        self.assertLessEqual(len(state['step']['questions']), 1)
        self.assertEqual(PersonalityJob.objects.filter(assessment_id=state['id'], kind='followup').count(), 2)
        self.assertEqual(complete.call_count, 1)

    def test_owner_revision_and_empty_pending_step_are_protected(self):
        state = self.core(); url = '/api/personality/assessments/'+state['id']
        other = Client(); other.force_login(self.bob)
        self.assertEqual(self.send(url, {'revision': state['revision'], 'action': 'skip_followup'}, client=other).status_code, 404)
        self.assertEqual(self.send(url, {'revision': state['revision'], 'answers': {}, 'complete': True}).status_code, 409)
        self.assertEqual(self.send(url, {'revision': state['revision']-1, 'action': 'skip_followup'}).status_code, 409)
        self.assertEqual(PersonalityJob.objects.filter(assessment_id=state['id']).count(), 1)
        response = self.client.get(url); self.assertIn('no-store', response['Cache-Control'])

    def test_payload_omits_fandom_and_account_and_preserves_raw_answer(self):
        state = self.core(); row = Assessment.objects.get(pk=state['id'])
        original = row.answers['open-conflict']['note'] + '我很喜欢动漫，也想匹配到鸣人。'
        row.answers['open-conflict']['note'] = original
        payload = source_payload(row); encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn('鸣人', encoded); self.assertNotIn(self.alice.username, encoded)
        self.assertNotIn('candidates', payload); self.assertNotIn('scores', payload)
        self.assertEqual(row.answers['open-conflict']['note'], original)
        long_note = '当时我先考虑了朋友的安排。'*100+'但是我其实更希望留出独处休息的时间。'
        row.answers['open-conflict']['note'] = long_note
        self.assertEqual(source_payload(row)['answers']['open-conflict']['note'], long_note)

    def test_interrupted_job_preserves_position_for_retry(self):
        state = self.core(); job = self.job(state)
        job.status = 'processing'; job.claim_token = 'old-claim'; job.updated_at = (timezone.now()-timedelta(minutes=20)).isoformat(); job.save()
        recover_jobs(); job.refresh_from_db()
        self.assertEqual(job.status, 'failed'); self.assertEqual(self.latest(state)['step']['ai_followup']['state'], 'unavailable')

    def test_daily_followup_budget_survives_assessment_deletion(self):
        state = self.core(); self.assertEqual(DailyUsage.objects.get(user=self.alice).followup_requests, 1)
        self.client.delete('/api/personality/assessments/'+state['id'])
        DailyUsage.objects.filter(user=self.alice).update(followup_requests=10)
        state = self.core()
        self.assertEqual(state['step']['ai_followup']['state'], 'fallback')
        self.assertFalse(PersonalityJob.objects.filter(assessment_id=state['id']).exists())
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 0)

    @patch('apps.personality.provider._request')
    def test_deepseek_followup_disables_thinking_without_changing_report_transport(self, request):
        request.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"done":true}'}}]}
        settings = PersonalitySettings(ai_enabled=True, base_url='https://api.deepseek.com/v1', model='deepseek-flash', max_output_tokens=1200)
        complete_json(settings, '访谈', {'purpose': 'personality_followup'})
        body = request.call_args.args[2]
        self.assertEqual(body['thinking'], {'type': 'disabled'}); self.assertNotIn('reasoning_effort', body)
        self.assertEqual(body['max_tokens'], 1200)
