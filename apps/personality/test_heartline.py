import copy
from unittest.mock import patch
from django.test import TestCase

from . import tests as fixtures
from . import test_analysis as reports
from .analysis import source_answers,validate_persona
from .heartline import validate_heartline,verify_originals
from .models import DailyUsage,PersonalityJob,PersonalitySettings
from .services import build_report,process_job
from .traits import TOPICS


class HeartlineTests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp
    send=fixtures.PersonalityTests.send
    create=fixtures.PersonalityTests.create
    finish=fixtures.PersonalityTests.finish
    character=fixtures.PersonalityTests.character

    def line(self,row):
        return {'text':'理解别人，也给自己的需要留一点位置。','question_id':'open-conflict','source_quote':row.answers['open-conflict']['note']}

    def test_refined_text_is_separate_from_literal_quote_and_answers(self):
        row=self.finish();source,_=source_answers(row);original=copy.deepcopy(row.answers)
        result=reports.persona_fixture(row,build_report(row));result['heartline']=self.line(row)
        clean=validate_persona(result,source,build_report(row))
        self.assertEqual(clean['heartline']['origin'],'ai_refined');self.assertEqual(clean['heartline']['text'],result['heartline']['text'])
        self.assertEqual(clean['quote']['text'],row.answers['open-conflict']['note']);self.assertEqual(row.answers,original)
        self.assertNotEqual(clean['heartline']['text'],clean['quote']['text'])

    def test_invalid_optional_copy_is_omitted_without_losing_valid_report(self):
        row=self.finish();source,_=source_answers(row);before=build_report(row);valid=reports.persona_fixture(row,before)
        variants=[None,[],{'text':'没有来源的句子'}, {**self.line(row),'question_id':'invented'},
                  {**self.line(row),'source_quote':'这句话不是用户的原文。'}, {**self.line(row),'text':'我是100%确定的完美人格。'},
                  {**self.line(row),'text':'<script>unsafe text</script>'}, {**self.line(row),'text':'字'*61}]
        for line in variants:
            with self.subTest(line_type=type(line).__name__):
                candidate={**valid,'heartline':line};clean=validate_persona(candidate,source,before)
                self.assertEqual(clean['heartline'],{});self.assertEqual(len(clean['sections']),10)
        for quote in [[],{'text':'这句话并不是用户说过的原话。','question_id':'open-conflict'}]:
            clean=validate_persona({**valid,'quote':quote},source,before)
            self.assertEqual(clean['quote']['text'],'');self.assertEqual(len(clean['sections']),10)

    def test_skipped_answer_and_stitched_source_are_not_accepted(self):
        row=self.finish();source,_=source_answers(row);source['open-conflict']['skipped']=True
        self.assertEqual(validate_heartline(self.line(row),source),{})
        literal='我想照顾自己。我也在意朋友。'
        report={'quote':{'text':literal,'question_id':'q'},'heartline':{'text':'理解别人，也照顾自己。','source_quote':literal,'question_id':'q'}}
        verify_originals(report,{'q':{'note':'我想照顾自己。这里有一段被过滤的内容。我也在意朋友。'}})
        self.assertFalse(report['quote']['text']);self.assertFalse(report['heartline'])

    @patch('apps.personality.services.complete_json')
    def test_summary_piggybacks_heartline_without_extra_call_or_score_changes(self,complete):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character();row=self.finish(consent=True)
        before=build_report(row);valid=reports.persona_fixture(row,before);valid['heartline']=self.line(row);calls=[]
        def reply(settings,prompt,payload):
            batch=payload.get('batch','match');calls.append(batch)
            if batch in ['inner','daily']:return {'sections':[s for s in valid['sections'] if s['topic'] in payload['topics']]}
            if batch=='summary':self.assertIn('heartline',prompt);return {k:v for k,v in valid.items() if k!='sections'}
            return reports.match_fixture(role)
        complete.side_effect=reply;self.send(f'/api/personality/assessments/{row.pk}/submit');job=PersonalityJob.objects.get(assessment=row)
        process_job(job.pk);row.refresh_from_db();self.assertEqual(row.status,'completed')
        self.assertEqual(calls,['inner','daily','summary','match']);self.assertEqual(row.report['heartline']['text'],valid['heartline']['text'])
        self.assertEqual(row.report['axes'],before['axes']);self.assertEqual(row.report['dimensions'],before['dimensions'])
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports,1)

    @patch('apps.personality.services.complete_json')
    def test_all_topics_without_summary_are_reused_as_sections_not_mistaken_for_full_persona(self,complete):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character();row=self.finish(consent=True)
        valid=reports.persona_fixture(row,build_report(row));calls=[]
        def reply(settings,prompt,payload):
            batch=payload.get('batch','match');calls.append(batch)
            if batch=='inner':return {'sections':[{**s,'topic':TOPICS[s['topic']]} for s in valid['sections']]}
            if batch=='summary':return {k:v for k,v in valid.items() if k!='sections'}
            return reports.match_fixture(role)
        complete.side_effect=reply;self.send(f'/api/personality/assessments/{row.pk}/submit');job=PersonalityJob.objects.get(assessment=row)
        process_job(job.pk);row.refresh_from_db();self.assertEqual(row.status,'completed');self.assertEqual(calls,['inner','summary','match'])
        self.assertEqual(len(row.report['sections']),10)

    @patch('apps.personality.services.complete_json')
    def test_existing_report_backfill_only_adds_heartline(self,complete):
        PersonalitySettings.objects.create(ai_enabled=True);self.character();row=self.finish(consent=True)
        row.report=build_report(row);row.status='completed';row.save();before=copy.deepcopy(row.report);answers=copy.deepcopy(row.answers)
        complete.return_value={'heartline':self.line(row)}
        job=PersonalityJob.objects.create(kind='report',assessment=row,requested_by=self.alice.username,parameters={'heartline_only':True})
        process_job(job.pk);row.refresh_from_db();job.refresh_from_db();self.assertEqual(job.status,'completed')
        self.assertEqual(row.status,'completed');self.assertEqual(row.answers,answers)
        self.assertEqual({k:v for k,v in row.report.items() if k!='heartline'},before)
        self.assertEqual(complete.call_count,1);self.assertLessEqual(complete.call_args.args[0].max_output_tokens,1200)
        self.assertFalse(DailyUsage.objects.exists())

    @patch('apps.personality.services.complete_json')
    def test_backfill_respects_consent_and_provider_failure_keeps_report_available(self,complete):
        PersonalitySettings.objects.create(ai_enabled=True);row=self.finish();row.report=build_report(row);row.status='completed';row.save()
        before=copy.deepcopy(row.report)
        job=PersonalityJob.objects.create(kind='report',assessment=row,requested_by=self.alice.username,parameters={'heartline_only':True})
        process_job(job.pk);complete.assert_not_called();row.refresh_from_db();self.assertEqual(row.report,before)
        row.ai_consent=True;row.save();complete.side_effect=ValueError('测试服务暂不可用')
        retry=PersonalityJob.objects.create(kind='report',assessment=row,requested_by=self.alice.username,parameters={'heartline_only':True})
        process_job(retry.pk);row.refresh_from_db();retry.refresh_from_db()
        self.assertEqual(retry.status,'failed');self.assertEqual(row.status,'completed');self.assertEqual(row.report,before)
