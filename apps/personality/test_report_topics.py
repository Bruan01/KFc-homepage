import copy
from unittest.mock import patch
from django.test import TestCase

from . import tests as fixtures
from . import test_analysis as reports
from .analysis import source_answers,validate_sections
from .models import PersonalitySettings,PersonalityJob
from .persona_pipeline import GROUPS
from .services import build_report,process_job
from .traits import TOPICS


class ReportTopicTests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp
    send=fixtures.PersonalityTests.send
    create=fixtures.PersonalityTests.create
    finish=fixtures.PersonalityTests.finish
    character=fixtures.PersonalityTests.character

    def test_chinese_and_english_topics_normalize_without_changing_content_or_evidence(self):
        row=self.finish();source,_=source_answers(row);valid=reports.persona_fixture(row,build_report(row));topics=GROUPS[1][1]
        sections=[copy.deepcopy(s) for s in valid['sections'] if s['topic'] in topics]
        for i,s in enumerate(sections):
            if i%2==0:s['topic']=TOPICS[s['topic']]
        result=validate_sections({'sections':list(reversed(sections))},source,topics)
        self.assertEqual([s['topic'] for s in result],topics)
        self.assertTrue(all(s['text']==valid['sections'][5]['text'] and s['evidence']==['open-conflict'] for s in result))

    def test_alias_support_does_not_accept_duplicates_missing_topics_or_forged_evidence(self):
        row=self.finish();source,_=source_answers(row);valid=reports.persona_fixture(row,build_report(row));topics=GROUPS[1][1]
        sections=[s for s in valid['sections'] if s['topic'] in topics]
        for kind in ['duplicate','unknown','missing','forged','numeric','malformed']:
            candidate=copy.deepcopy(sections)
            if kind=='duplicate':candidate[1]['topic']=TOPICS[candidate[0]['topic']]
            elif kind=='unknown':candidate[0]['topic']='未知主题'
            elif kind=='missing':candidate.pop()
            elif kind=='forged':candidate[0]['evidence']=['invented-answer']
            elif kind=='numeric':candidate[0]['text']='你的人格匹配概率为99%，这个数字是虚构的。'
            elif kind=='malformed':candidate[0]['topic']=['learning']
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_sections({'sections':candidate},source,topics)

    @patch('apps.personality.services.complete_json')
    def test_complete_report_accepts_realistic_chinese_batch_topics(self,complete):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character();row=self.finish(consent=True)
        before=build_report(row);original=copy.deepcopy(row.answers);valid=reports.persona_fixture(row,before);calls=[]
        def reply(settings,prompt,payload):
            calls.append(payload.get('batch','match'))
            if payload.get('batch') in ['inner','daily']:
                sections=[{**s,'topic':TOPICS[s['topic']]} for s in valid['sections'] if s['topic'] in payload['topics']]
                return {'sections':sections}
            if payload.get('batch')=='summary':return {key:value for key,value in valid.items() if key!='sections'}
            return reports.match_fixture(role)
        complete.side_effect=reply;self.send(f'/api/personality/assessments/{row.pk}/submit');job=PersonalityJob.objects.get(assessment=row)
        process_job(job.pk);row.refresh_from_db();job.refresh_from_db()
        self.assertEqual(job.status,'completed');self.assertEqual(row.status,'completed');self.assertEqual(calls,['inner','daily','summary','match'])
        self.assertEqual([s['topic'] for s in row.report['sections']],list(TOPICS))
        self.assertEqual(row.answers,original);self.assertEqual(row.report['axes'],before['axes']);self.assertEqual(row.report['dimensions'],before['dimensions'])
        self.assertEqual(row.report['character']['id'],role.pk)
