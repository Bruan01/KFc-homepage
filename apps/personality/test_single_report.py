"""Billing-sensitive single-call journeys and bounded repair, with synthetic AI."""
import copy
import io
import json
import urllib.error
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from django.test import TestCase, SimpleTestCase

from . import tests as fixtures
from .models import Assessment, Character, DailyUsage, PersonalityJob
from .services import build_report, process_job, eligible_characters
from .analysis import source_answers
from .single_report import POLICY, compact_answers, candidate_pool, anonymous_candidates, generate
from .provider import AnalysisUnavailable, complete_json, encrypt_key
from .test_analysis import persona_fixture, match_fixture


class SingleReportJourneyTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    character = fixtures.PersonalityTests.character
    finish = fixtures.PersonalityTests.finish
    create = fixtures.PersonalityTests.create

    def public_finish(self):
        fixtures.ready_ai_fixture()
        response=self.send('/api/personality/assessments',{'ai_consent':True})
        self.assertEqual(response.status_code,201,response.content)
        state=response.json();endpoint='/api/personality/assessments/'+state['id']
        with patch('apps.personality.services.complete_json') as complete:
            while state['status']=='active':
                self.assertTrue(state['step']['questions'])
                self.assertNotIn('ai_followup',state['step'])
                answers={q['id']:{'value':5 if q['kind']=='scale' else None,'note':'','skipped':False,
                         **({'choice':'option-1'} if q.get('options') else {})} for q in state['step']['questions']}
                response=self.send(endpoint,{'revision':state['revision'],'answers':answers,'complete':True})
                self.assertEqual(response.status_code,200,response.content)
                state=response.json()
            complete.assert_not_called()
        self.assertFalse(PersonalityJob.objects.filter(assessment_id=state['id']).exists())
        self.assertFalse(DailyUsage.objects.filter(user=self.alice,followup_requests__gt=0).exists())
        return Assessment.objects.get(pk=state['id'])

    def combined(self,row,payload):
        result=persona_fixture(row,build_report(row))
        result['quote']={}
        result['heartline']={'question_id':'open-conflict','choice_id':'option-1','text':'我想先照顾好自己的安排，再决定能帮忙多少。'}
        pool=payload['character_candidates']
        result['match']=None
        if pool:
            selected=next((c for c in pool if c['id']==self.role.pk),pool[0])
            match=match_fixture(self.role);match['character_id']=selected['id']
            for key in ('similarities','differences'):
                for item in match[key]:item['character_evidence']=[next(iter(selected['references']))]
            result['match']=match
        return result

    def submit(self,row):
        response=self.send(f'/api/personality/assessments/{row.pk}/submit')
        self.assertEqual(response.status_code,202,response.content)
        return PersonalityJob.objects.get(assessment=row,kind='report',status='queued')

    def prepare(self,with_role=True):
        row=self.public_finish()
        self.role=self.character() if with_role else None
        return row

    def test_public_journey_uses_zero_ai_while_answering_and_one_for_complete_report(self):
        row=self.prepare();original=copy.deepcopy(row.answers);before=build_report(row)
        observed=[]
        def reply(settings,prompt,payload):
            observed.append(payload)
            self.assertTrue(settings._single_request)
            self.assertLessEqual(settings.max_output_tokens,6000)
            self.assertEqual(payload['purpose'],'personality_report')
            self.assertTrue(all('note' not in answer for answer in payload['answers'].values()))
            self.assertTrue(all('skipped' not in answer and 'choice' not in answer for answer in payload['answers'].values()))
            self.assertNotIn(self.role.name,json.dumps(payload['character_candidates'],ensure_ascii=False))
            return self.combined(row,payload)
        with patch('apps.personality.services.complete_json',side_effect=reply) as complete:
            process_job(self.submit(row).pk)
            self.assertEqual(complete.call_count,1)
        row.refresh_from_db();self.assertEqual(row.status,'completed')
        self.assertEqual(row.report['character']['id'],self.role.pk)
        self.assertEqual(len(row.report['sections']),10)
        self.assertEqual(row.report['axes'],before['axes']);self.assertEqual(row.report['dimensions'],before['dimensions'])
        self.assertEqual(row.report['heartline']['origin'],'ai_from_choices')
        self.assertEqual(row.report['audit']['single_report']['requests'],1)
        self.assertEqual(row.answers,original)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports,1)

    def test_repair_only_requests_bad_topic_and_match_and_does_not_overwrite_valid_content(self):
        row=self.prepare();responses=[]
        def reply(settings,prompt,payload):
            result=self.combined(row,payload);responses.append(copy.deepcopy(payload))
            if len(responses)==1:
                result['sections']=[s for s in result['sections'] if s['topic']!='emotion']
                result['match']['character_id']=999999
            else:
                self.assertEqual(set(payload['requested']),{'sections:emotion','match'})
                result['title']='不应覆盖已通过的人格名称'
                result['sections']=[{**s,'text':'不应覆盖已通过的主题内容与原有的真实依据。'} for s in result['sections']]
            return result
        with patch('apps.personality.services.complete_json',side_effect=reply) as complete:
            process_job(self.submit(row).pk);self.assertEqual(complete.call_count,2)
        row.refresh_from_db();self.assertEqual(row.status,'completed')
        self.assertEqual(row.report['title'],'温柔而有边界的理解者')
        self.assertNotIn('不应覆盖',row.report['sections'][0]['text'])

    def test_two_failed_repairs_stop_and_manual_retry_reuses_paid_parts_and_allowance(self):
        row=self.prepare();seen=[]
        def incomplete(settings,prompt,payload):
            seen.append(payload['requested']);result=self.combined(row,payload);result.pop('match');return result
        with patch('apps.personality.services.complete_json',side_effect=incomplete) as complete:
            job=self.submit(row);process_job(job.pk);self.assertEqual(complete.call_count,2)
        row.refresh_from_db();job.refresh_from_db()
        self.assertEqual(row.status,'failed');self.assertEqual(seen[1],['match'])
        self.assertEqual(len(job.checkpoint['single_report']['sections']),10)
        def repair(settings,prompt,payload):
            self.assertEqual(payload['requested'],['match'])
            return {'match':self.combined(row,payload)['match']}
        with patch('apps.personality.services.complete_json',side_effect=repair) as complete:
            process_job(self.submit(row).pk);self.assertEqual(complete.call_count,1)
        row.refresh_from_db();self.assertEqual(row.status,'completed')
        self.assertEqual(row.report['audit']['single_report']['requests'],3)
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports,1)

    def test_truncated_output_gets_only_one_compact_retry(self):
        row=self.prepare();calls=[]
        def reply(settings,prompt,payload):
            calls.append(payload)
            if len(calls)==1:raise AnalysisUnavailable('截断',reason='truncated')
            return self.combined(row,payload)
        with patch('apps.personality.services.complete_json',side_effect=reply) as complete:
            process_job(self.submit(row).pk);self.assertEqual(complete.call_count,2)
        row.refresh_from_db();self.assertEqual(row.status,'completed')
        self.assertEqual(calls[1]['batch'],'repair')

    def test_network_error_is_not_silently_retried(self):
        row=self.prepare();original=copy.deepcopy(row.answers)
        with patch('apps.personality.services.complete_json',side_effect=AnalysisUnavailable('连接超时',retryable=True)) as complete:
            process_job(self.submit(row).pk);self.assertEqual(complete.call_count,1)
        row.refresh_from_db();self.assertEqual(row.status,'failed');self.assertEqual(row.answers,original)

    def test_empty_character_library_still_generates_personality_with_one_request(self):
        row=self.prepare(with_role=False)
        with patch('apps.personality.services.complete_json',side_effect=lambda settings,prompt,payload:self.combined(row,payload)) as complete:
            process_job(self.submit(row).pk);self.assertEqual(complete.call_count,1)
        row.refresh_from_db();self.assertEqual(row.status,'completed');self.assertIsNone(row.report['character'])

    def test_candidates_are_bounded_and_current_publication_is_rechecked(self):
        row=self.prepare()
        for i in range(10):self.character(name=f'候选人物{i}',work_name=f'候选作品{i}')
        packets,scoped=anonymous_candidates(candidate_pool(build_report(row),eligible_characters(),str(row.pk)))
        self.assertEqual(len(packets),6)
        self.assertTrue(all(len(c['references'])<=4 for c in packets))
        self.assertTrue(all('image_url' not in c and 'profile' not in c and 'name' not in c for c in packets))
        # A chosen role withdrawn while the upstream request runs cannot publish.
        def withdraw(settings,prompt,payload):
            result=self.combined(row,payload)
            Character.objects.filter(pk=result['match']['character_id']).update(status='rejected')
            return result
        with patch('apps.personality.services.complete_json',side_effect=withdraw):
            job=self.submit(row);process_job(job.pk)
        row.refresh_from_db();job.refresh_from_db();self.assertEqual(row.status,'failed')
        self.assertEqual(len(job.checkpoint['single_report']['sections']),10)
        self.assertNotIn('match',job.checkpoint['single_report'])

    def test_cached_legacy_batches_continue_instead_of_discarding_paid_analysis(self):
        row=self.finish(consent=True);row.steps[0]['analysis_policy']=POLICY;row.save(update_fields=['steps'])
        role=self.character();before=build_report(row);persona=persona_fixture(row,before)
        cache={'persona':persona}
        from .analysis import enrich
        with patch('apps.personality.single_report.generate') as single:
            result=enrich(row,before,fixtures.ready_ai_fixture(),lambda *args:match_fixture(role),[role],cache)
            single.assert_not_called()
        self.assertEqual(result['character']['id'],role.pk)

    def test_old_pending_interview_switches_to_bank_without_spending_another_request(self):
        from .test_followups import FollowupWorkflowTests
        old=FollowupWorkflowTests(methodName='test_two_turns_use_fresh_reply_and_preserve_scores_and_refresh')
        old.client=self.client;old.alice=self.alice
        state=old.core()
        row=Assessment.objects.get(pk=state['id']);original=copy.deepcopy(row.answers)
        row.steps[0].pop('analysis_policy',None);row.save(update_fields=['steps'])
        job=PersonalityJob.objects.get(assessment=row,kind='followup',status='queued')
        from .followups import fingerprint
        job.parameters['fingerprint']=fingerprint(row);job.save(update_fields=['parameters'])
        with patch('apps.personality.services.complete_json') as complete:
            process_job(job.pk);complete.assert_not_called()
        row.refresh_from_db();job.refresh_from_db()
        self.assertEqual(row.answers,original);self.assertEqual(job.status,'completed')
        self.assertTrue(row.steps[row.step_index]['questions'])
        self.assertTrue(all(q.get('options') for q in row.steps[row.step_index]['questions']))

    def test_unstarted_old_report_without_policy_uses_single_call_too(self):
        row=self.prepare();row.steps[0].pop('analysis_policy');row.save(update_fields=['steps'])
        with patch('apps.personality.services.complete_json',side_effect=lambda settings,prompt,payload:self.combined(row,payload)) as complete:
            job=self.submit(row);job.checkpoint={'persona_parts':{}};job.save(update_fields=['checkpoint'])
            process_job(job.pk);self.assertEqual(complete.call_count,1)
        row.refresh_from_db();self.assertEqual(row.status,'completed')

    def test_synthetic_payload_comparison_removes_repeated_inputs_without_calling_an_api(self):
        from .analysis import enrich
        row=self.prepare();before=build_report(row);settings=fixtures.ready_ai_fixture()
        persona=persona_fixture(row,before);persona['quote']={};legacy=[];combined=[]
        row.steps[0]['analysis_policy']='legacy-batches'
        def batches(config,prompt,payload):
            legacy.append((prompt,payload))
            if payload['purpose']=='personality_character_match':return match_fixture(self.role)
            if payload['batch']=='summary':return persona
            return {'sections':[s for s in persona['sections'] if s['topic'] in payload['topics']]}
        enrich(row,copy.deepcopy(before),settings,batches,[self.role])
        row.steps[0]['analysis_policy']=POLICY
        def once(config,prompt,payload):
            combined.append((prompt,payload));return self.combined(row,payload)
        enrich(row,copy.deepcopy(before),settings,once,[self.role])
        self.assertEqual(len(legacy),4);self.assertEqual(len(combined),1)
        size=lambda items:sum(len(prompt)+len(json.dumps(payload,ensure_ascii=False,separators=(',',':'))) for prompt,payload in items)
        self.assertLess(size(combined),size(legacy))

    def test_real_local_http_transport_sends_exactly_one_completion_and_records_usage(self):
        from .configuration import remember_connection_check
        row=self.prepare();requests=[]
        packets,_=anonymous_candidates(candidate_pool(build_report(row),eligible_characters(),str(row.pk)))
        response=self.combined(row,{'character_candidates':packets})
        class Handler(BaseHTTPRequestHandler):
            def do_POST(handler):
                body=json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
                requests.append(body)
                encoded=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(response,ensure_ascii=False)}}],
                                    'usage':{'prompt_tokens':123,'completion_tokens':456,'total_tokens':579}},ensure_ascii=False).encode()
                handler.send_response(200);handler.send_header('Content-Type','application/json');handler.end_headers();handler.wfile.write(encoded)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            settings=fixtures.ready_ai_fixture();settings.base_url=f'http://127.0.0.1:{server.server_port}/v1';settings.save();remember_connection_check(settings,'passed')
            process_job(self.submit(row).pk)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
        row.refresh_from_db();self.assertEqual(row.status,'completed')
        self.assertEqual(len(requests),1)
        self.assertEqual(json.loads(requests[0]['messages'][1]['content'])['purpose'],'personality_report')
        call=row.analysis_calls.get();self.assertEqual(call.usage['total_tokens'],579)


class SingleReportTransportTests(SimpleTestCase):
    def test_compaction_keeps_whole_notes_and_marks_or_omits_unread_text(self):
        source={str(i):{'kind':'open','question':'具体的题目','note':'保留条件和否定。'*300,'selection':{'id':'option-1','text':'具体选项'}} for i in range(4)}
        original=copy.deepcopy(source);compact=compact_answers(source)
        self.assertLessEqual(sum(len(a['note']) for a in compact.values()),6000)
        self.assertTrue(any(a.get('note_omitted') for a in compact.values()))
        self.assertTrue(all(not a['note'] or a['note']==original[key]['note'] for key,a in compact.items()))
        self.assertEqual(source,original)

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_official_deepseek_combined_report_has_no_hidden_reasoning_or_length_retry(self,opener):
        from .models import PersonalitySettings
        settings=PersonalitySettings(ai_enabled=True,base_url='https://api.deepseek.com/v1',model='deepseek-flash',api_key_ciphertext=encrypt_key('fixture-key'))
        settings._single_request=True
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'length','message':{'content':'{"partial":'}}]}).encode()
        opener.return_value.open.return_value=response
        with self.assertRaises(AnalysisUnavailable) as caught:
            complete_json(settings,'简洁报告',{'purpose':'personality_report','batch':'complete'})
        self.assertEqual(caught.exception.reason,'truncated');self.assertEqual(opener.return_value.open.call_count,1)
        body=json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertEqual(body['thinking'],{'type':'disabled'});self.assertNotIn('reasoning_effort',body)

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_rejected_token_parameter_does_not_bypass_single_request_budget(self,opener):
        from .models import PersonalitySettings
        settings=PersonalitySettings(ai_enabled=True,base_url='https://example.invalid/v1',model='fixture',api_key_ciphertext=encrypt_key('fixture-key'))
        settings._single_request=True
        opener.return_value.open.side_effect=urllib.error.HTTPError(settings.base_url,400,'bad',{},io.BytesIO(b'{"error":{"param":"max_tokens"}}'))
        with self.assertRaises(AnalysisUnavailable):complete_json(settings,'报告',{'purpose':'personality_report'})
        self.assertEqual(opener.return_value.open.call_count,1)
