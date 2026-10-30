import copy
import io
import json
import urllib.error
from datetime import timedelta
from unittest.mock import MagicMock,patch

from django.test import TestCase,Client
from django.utils import timezone

from . import tests as fixtures
from . import test_analysis as reports
from . import plain_bank as scenario_bank
from . import questions
from .models import Assessment,PersonalityJob,PersonalitySettings,AnalysisCall
from .provider import complete_json,encrypt_key,AnalysisUnavailable
from .services import build_report,process_job
from .tracing import record_calls


class ExplorationV3Tests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp
    send=fixtures.PersonalityTests.send
    create=fixtures.PersonalityTests.create
    finish=fixtures.PersonalityTests.finish
    character=fixtures.PersonalityTests.character

    def test_scene_pool_keeps_polarity_and_stored_questions_survive_changes(self):
        from .question_bank import BASE_EXTRA,EXTENDED_EXTRA
        for original,extra,scenes in [(questions.BASE,BASE_EXTRA,scenario_bank.BASE),(questions.EXTENDED,EXTENDED_EXTRA,scenario_bank.EXTENDED)]:
            for target,items in original.items():self.assertEqual(len(items+extra[target]),len(scenes[target]))
        before=self.create();row=Assessment.objects.get(pk=before['id']);stored=copy.deepcopy(row.steps)
        self.assertEqual(row.version,questions.VERSION)
        for step in stored:
            for item in step['questions']:
                if item['kind']!='scale':continue
                prefix,target,index=item['id'].split('-');index=int(index)
                original=(questions.BASE[target]+BASE_EXTRA[target]) if prefix=='base' else (questions.EXTENDED[target]+EXTENDED_EXTRA[target])
                self.assertEqual(item['reverse'],original[index][1]);self.assertEqual(item['wording_version'],questions.VERSION)
        with patch.dict(scenario_bank.BASE,{'IE':['changed']*12}):
            self.assertEqual(self.client.get('/api/personality/assessments/'+str(row.pk)).json()['step'],stored[0])

    @patch('apps.personality.services.complete_json')
    def test_batches_resume_after_failure_without_repeating_accepted_sections(self,complete):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character();row=self.finish(consent=True,context=True);before=build_report(row);valid=reports.persona_fixture(row,before)
        calls=[];fail=True
        def answer(config,prompt,payload):
            key=payload.get('batch');calls.append(key or 'match')
            if key=='daily' and fail:raise AnalysisUnavailable('测试连接中断')
            if key in {'inner','daily'}:return {'sections':[item for item in valid['sections'] if item['topic'] in payload['topics']]}
            if key=='summary':return {k:v for k,v in valid.items() if k!='sections'}
            return reports.match_fixture(role)
        complete.side_effect=answer;endpoint=f'/api/personality/assessments/{row.pk}/submit'
        self.assertEqual(self.send(endpoint).status_code,202);job=PersonalityJob.objects.get(assessment=row);process_job(job.pk);job.refresh_from_db()
        self.assertEqual(job.status,'failed');self.assertEqual(calls,['inner','daily'])
        first=copy.deepcopy(job.checkpoint['persona_parts']['inner']);self.assertEqual(len(first),5)
        self.assertNotIn('daily',job.checkpoint['persona_parts']);original=copy.deepcopy(row.answers)
        fail=False;calls.clear();self.send(endpoint);retry=PersonalityJob.objects.get(assessment=row,status='queued');process_job(retry.pk)
        row.refresh_from_db();self.assertEqual(row.status,'completed');self.assertEqual(calls,['daily','summary','match'])
        self.assertEqual(row.report['sections'][:5],first);self.assertEqual(row.answers,original)
        self.assertEqual(row.report['axes'],before['axes']);self.assertEqual(row.report['dimensions'],before['dimensions'])
        self.assertEqual(row.report['character']['id'],role.pk)

    @patch('apps.personality.services.complete_json')
    def test_invalid_evidence_is_not_saved_as_a_completed_batch(self,complete):
        PersonalitySettings.objects.create(ai_enabled=True);row=self.finish(consent=True,context=True);valid=reports.persona_fixture(row,build_report(row))
        def answer(config,prompt,payload):
            sections=copy.deepcopy([item for item in valid['sections'] if item['topic'] in payload['topics']]);sections[0]['evidence']=['invented-answer'];return {'sections':sections}
        complete.side_effect=answer;self.send(f'/api/personality/assessments/{row.pk}/submit');job=PersonalityJob.objects.get(assessment=row);process_job(job.pk);job.refresh_from_db()
        self.assertEqual(job.status,'failed');self.assertNotIn('inner',job.checkpoint.get('persona_parts',{}))

    def test_old_report_can_add_a_character_without_reanswering_or_ai_consent(self):
        row=self.finish();before=build_report(row);before['character']=None;row.report=before;row.status='completed';row.save()
        role=self.character();original=copy.deepcopy(row.answers)
        self.assertTrue(self.client.get(f'/api/personality/assessments/{row.pk}/report').json()['can_add_character'])
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/complete-character').status_code,202)
        job=PersonalityJob.objects.get(assessment=row);self.assertFalse(job.parameters['ai']);process_job(job.pk);row.refresh_from_db()
        self.assertEqual(row.report['character']['id'],role.pk);self.assertEqual(row.answers,original)
        self.assertEqual(row.report['axes'],before['axes']);self.assertEqual(row.report['dimensions'],before['dimensions']);self.assertFalse(row.ai_consent)


class AnalysisTraceTests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp

    def prepare(self):
        row=Assessment.objects.create(user=self.alice,ai_consent=True)
        job=PersonalityJob.objects.create(assessment=row,kind='report',requested_by=self.alice.username)
        settings=PersonalitySettings(ai_enabled=True,base_url='https://api.deepseek.com/v1',model='deepseek-flash',api_key_ciphertext=encrypt_key('trace-test-secret'),max_output_tokens=8000)
        return row,job,settings

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_physical_requests_capture_retry_usage_and_hide_credentials_and_reasoning(self,opener):
        row,job,settings=self.prepare();response=MagicMock()
        def envelope(reason,content):return json.dumps({'choices':[{'finish_reason':reason,'message':{'content':content,'reasoning_content':'hidden-private-reasoning'}}],'usage':{'completion_tokens':8000}}).encode()
        response.__enter__.return_value.read.side_effect=[envelope('length','{"partial":'),envelope('stop','{"ok":true,"echo":"trace-test-secret"}')]
        opener.return_value.open.return_value=response
        with record_calls(row.pk,job.pk):complete_json(settings,'测试完整 JSON',{'purpose':'personality_analysis','batch':'inner','answers':{'fixture':'trace-test-secret'}})
        calls=list(row.analysis_calls.all());self.assertEqual(len(calls),2)
        self.assertEqual([call.status for call in calls],['truncated','returned'])
        self.assertEqual(calls[0].request['thinking'],{'type':'enabled'});self.assertEqual(calls[1].request['thinking'],{'type':'disabled'})
        for call in calls:
            encoded=json.dumps([call.request,call.response]);self.assertNotIn('trace-test-secret',encoded);self.assertNotIn('hidden-private-reasoning',encoded)
            self.assertNotIn('Authorization',encoded);self.assertEqual(call.request['max_tokens'],8000);self.assertEqual(call.usage['completion_tokens'],8000)

    @patch('apps.personality.provider.urllib.request.build_opener')
    def test_failed_http_does_not_store_upstream_error_body(self,opener):
        row,job,settings=self.prepare();opener.return_value.open.side_effect=urllib.error.HTTPError(settings.base_url,401,'upstream-private',{},io.BytesIO(b'trace-test-secret'))
        with record_calls(row.pk,job.pk):
            with self.assertRaises(AnalysisUnavailable):complete_json(settings,'test',{'purpose':'personality_analysis'})
        call=row.analysis_calls.get();self.assertEqual(call.status,'error');self.assertIn('401',call.error)
        self.assertNotIn('upstream-private',call.error);self.assertEqual(call.response,{})

    def test_trace_endpoints_are_owner_or_super_admin_only_and_private(self):
        row,job,_=self.prepare();AnalysisCall.objects.create(assessment=row,job=job,stage='test',request={'messages':[]})
        endpoint=f'/api/personality/assessments/{row.pk}/analysis'
        response=self.client.get(endpoint);self.assertEqual(response.status_code,200);self.assertIn('no-store',response['Cache-Control'])
        self.client.force_login(self.bob);self.assertEqual(self.client.get(endpoint).status_code,404)
        self.assertEqual(self.client.get(f'/personality/analysis/{row.pk}').status_code,404)
        guest=Client();self.assertEqual(guest.get(endpoint).status_code,401)
        limited=Client();s=limited.session;s['admin_username']='limited';s['admin_level']=3;s['admin_is_super']=False;s.save()
        for url in ['/api/admin/personality/reports',f'/api/admin/personality/reports/{row.pk}/analysis']:
            self.assertEqual(limited.get(url).status_code,403);self.assertEqual(self.admin.get(url).status_code,200)

    def test_old_records_are_hidden_and_cleaned_and_owner_deletion_cascades(self):
        row,job,_=self.prepare();AnalysisCall.objects.create(assessment=row,job=job,stage='old',created_at=(timezone.now()-timedelta(days=31)).isoformat())
        self.assertEqual(self.client.get(f'/api/personality/assessments/{row.pk}/analysis').json()['total_calls'],0)
        with record_calls(row.pk,job.pk):pass
        self.assertFalse(AnalysisCall.objects.exists())
        AnalysisCall.objects.create(assessment=row,job=job,stage='new');row.delete();self.assertFalse(AnalysisCall.objects.exists())
