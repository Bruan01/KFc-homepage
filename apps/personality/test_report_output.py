"""Report transport recovery must preserve answers, evidence, scoring and checkpoints."""
import copy
import json
from unittest.mock import patch

from django.test import TestCase

from . import tests as assessment_fixtures
from . import test_analysis as report_fixtures
from .models import DailyUsage,PersonalityJob,PersonalitySettings
from .services import build_report,process_job


def response(result,reason='stop'):
    return {'choices':[{'finish_reason':reason,'message':{'content':json.dumps(result,ensure_ascii=False)}}]}


class ReportOutputTests(TestCase):
    setUpTestData=classmethod(assessment_fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=assessment_fixtures.PersonalityTests.setUp
    send=assessment_fixtures.PersonalityTests.send
    create=assessment_fixtures.PersonalityTests.create
    finish=assessment_fixtures.PersonalityTests.finish
    character=assessment_fixtures.PersonalityTests.character

    def prepare(self):
        PersonalitySettings.objects.create(ai_enabled=True,base_url='https://api.deepseek.com/v1',model='deepseek-flash',max_output_tokens=8000)
        role=self.character()
        row=self.finish(consent=True,context=True)
        return row,role,build_report(row)

    @patch('apps.personality.provider._request')
    def test_truncated_persona_recovers_to_a_full_report_with_one_app_quota_charge(self,request):
        row,role,before=self.prepare();original=copy.deepcopy(row.answers);bodies=[]
        def answer(config,path,body):
            bodies.append(copy.deepcopy(body));payload=json.loads(body['messages'][1]['content'])
            if payload['purpose']=='personality_analysis':
                if len(bodies)==1:return {'choices':[{'finish_reason':'length','message':{'content':'{"title":"partial'}}]}
                return response(report_fixtures.persona_fixture(row,before))
            return response(report_fixtures.match_fixture(role))
        request.side_effect=answer
        self.assertEqual(self.send(f'/api/personality/assessments/{row.pk}/submit').status_code,202)
        job=PersonalityJob.objects.get(assessment=row);process_job(job.pk)
        job.refresh_from_db();row.refresh_from_db()
        self.assertEqual(job.status,'completed');self.assertEqual(row.status,'completed')
        self.assertEqual(row.answers,original);self.assertEqual(row.report['axes'],before['axes'])
        self.assertEqual(row.report['dimensions'],before['dimensions']);self.assertEqual(len(row.report['sections']),10)
        self.assertEqual(row.report['character']['id'],role.pk)
        self.assertEqual(row.report['quote']['text'],original['open-conflict']['note'])
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports,1)
        self.assertEqual(len(bodies),3);self.assertEqual([body['max_tokens'] for body in bodies],[8000]*3)
        self.assertEqual(bodies[1]['thinking'],{'type':'disabled'})
        self.assertEqual(bodies[0]['messages'][1],bodies[1]['messages'][1]);self.assertEqual(job.checkpoint,{})

    @patch('apps.personality.provider._request')
    def test_repeated_match_truncation_saves_persona_and_manual_retry_resumes_it(self,request):
        row,role,before=self.prepare();original=copy.deepcopy(row.answers);purposes=[];allow_match=False
        def answer(config,path,body):
            purpose=json.loads(body['messages'][1]['content'])['purpose'];purposes.append(purpose)
            if purpose=='personality_analysis':return response(report_fixtures.persona_fixture(row,before))
            if allow_match:return response(report_fixtures.match_fixture(role))
            return {'choices':[{'finish_reason':'length','message':{'content':'{"character_id":'}}]}
        request.side_effect=answer
        endpoint=f'/api/personality/assessments/{row.pk}/submit'
        self.assertEqual(self.send(endpoint).status_code,202)
        job=PersonalityJob.objects.get(assessment=row);process_job(job.pk)
        row.refresh_from_db();job.refresh_from_db()
        self.assertEqual(row.status,'failed');self.assertEqual(row.answers,original)
        self.assertIn('persona',job.checkpoint);self.assertIn('pool',job.checkpoint);self.assertNotIn('match',job.checkpoint)
        self.assertIn('8000',job.error);self.assertEqual(len(purposes),3)
        allow_match=True;purposes.clear()
        self.assertEqual(self.send(endpoint).status_code,202)
        retry=PersonalityJob.objects.filter(assessment=row,status='queued').get();process_job(retry.pk)
        row.refresh_from_db();retry.refresh_from_db()
        self.assertEqual(purposes,['personality_character_match']);self.assertEqual(row.status,'completed')
        self.assertEqual(row.answers,original);self.assertEqual(row.report['axes'],before['axes'])
        self.assertEqual(row.report['dimensions'],before['dimensions']);self.assertEqual(retry.checkpoint,{})
