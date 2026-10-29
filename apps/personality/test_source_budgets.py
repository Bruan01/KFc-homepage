import copy
from unittest.mock import patch

from django.test import TestCase

from . import tests as fixtures
from . import test_workflow as workflow_fixtures
from .approvals import retained_approvals
from .catalog import profile_draft
from .evidence import supplement
from .evidence_context import analysis_context
from .models import Character,PersonalityJob,PersonalitySettings
from .review import review_ready
from .services import process_job
from .transfer import clean_record,export_catalog,import_catalog


class SourceBudgetTests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp
    send=fixtures.PersonalityTests.send
    character=fixtures.PersonalityTests.character
    act=workflow_fixtures.WorkflowTests.act

    def source(self,index):
        return {'url':f'https://example.com/plot/{index}','text':f'人物在第{index}段情境中遇到新的困难，调整策略并重新行动。这段是隔离测试用资料。'}

    def empty(self,*args,**kwargs):
        return {'sources':[],'cache':{},'status':'empty','queries':0,'fetched':0,'cached':0,'note':'没有新的测试资料'}

    def partial(self,draft,complete,retrieve):
        PersonalitySettings.objects.get_or_create(pk=1,defaults={'ai_enabled':True})
        role=self.character(status='candidate')
        draft.side_effect=lambda *args:copy.deepcopy(role.profile)
        complete.side_effect=None;complete.return_value=workflow_fixtures.review_fixture(role,bad_key='recovery')
        retrieve.side_effect=self.empty
        self.act('generate',[role.pk]);job=PersonalityJob.objects.filter(character=role).latest('created_at');process_job(job.pk)
        role.refresh_from_db()
        self.assertEqual(len(role.profile_check['dimension_approvals']),5)
        return role

    def test_twelve_sources_save_and_export_import_but_thirteen_are_rejected(self):
        role=self.character(status='draft');sources=[self.source(index) for index in range(12)]
        self.assertEqual(self.send(f'/api/admin/personality/characters/{role.pk}',{'extra_sources':sources},self.admin).status_code,200)
        payload=export_catalog();clean_record(payload['characters'][0])
        payload['characters'][0]['source_id']=999991;payload['characters'][0]['name']='迁移测试角色'
        self.assertEqual(import_catalog(payload)['imported'],1)
        self.assertEqual(len(Character.objects.get(source_id=999991).extra_sources),12)
        response=self.send(f'/api/admin/personality/characters/{role.pk}',{'extra_sources':sources+[self.source(12)]},self.admin)
        self.assertEqual(response.status_code,400);role.refresh_from_db();self.assertEqual(len(role.extra_sources),12)

    @patch('apps.personality.evidence._request')
    def test_acquisition_can_continue_past_five_and_stops_at_twelve(self,request):
        settings=PersonalitySettings(base_url='https://api.deepseek.com/v1',api_key_ciphertext='fixture')
        role=Character(source_id=1,name='人物甲',work_id=2,work_name='测试作品',source_url='https://bgm.tv/character/1')
        body='人物甲在测试作品的旅途中想出新的办法，在道路中断后试验替代路线，和朋友讨论并比较不同方案。'*5
        request.return_value={'results':[{'url':'https://zh.wikipedia.org/wiki/new_plot','title':'人物甲 测试作品','authority':3,'content':body}]}
        for count in [5,11]:
            role.extra_sources=[self.source(index) for index in range(count)]
            result=supplement(role,settings,['divergence'])
            self.assertEqual(len(result['sources']),1);self.assertLessEqual(count+len(result['sources']),12)
        role.extra_sources=[self.source(index) for index in range(12)]
        before=request.call_count;result=supplement(role,settings,['divergence'])
        self.assertEqual(result['status'],'full');self.assertEqual(request.call_count,before)

    @patch('apps.personality.catalog.complete_json')
    def test_twelve_stored_sources_do_not_expand_the_model_prompt_without_bound(self,complete):
        role=self.character();role.extra_sources=[{**self.source(index),'text':(self.source(index)['text']+'他会坚持练习，并思考不同的办法。')*100} for index in range(12)]
        context=analysis_context(role,['divergence'])
        self.assertGreaterEqual(context['material_selection']['selected_sources'],3)
        self.assertLessEqual(context['material_selection']['selected_sources'],5)
        self.assertLessEqual(sum(len(item['quote']) for item in context['evidence_catalog']),9000)
        self.assertTrue(all(any(item['quote'] in source['text'] for source in [{'text':role.source_text},*role.extra_sources]) for item in context['evidence_catalog']))
        complete.return_value=role.profile;profile_draft(role,PersonalitySettings())
        payload=complete.call_args.args[2]
        self.assertNotIn('extra_sources',payload);self.assertNotIn('source',payload)

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_accepted_dimensions_survive_another_job_and_new_unused_source(self,draft,complete,retrieve):
        role=self.partial(draft,complete,retrieve)
        self.assertEqual(self.send(f'/api/admin/personality/characters/{role.pk}',{'extra_sources':[self.source(4)]},self.admin).status_code,200)
        role.refresh_from_db();self.assertEqual(len(retained_approvals(role)),5)
        requests=[]
        def targeted(row,*args):
            requests.append(row._revision_targets)
            return {'dimensions':{'recovery':{**role.profile['dimensions']['recovery'],'level':6},'empathy':{**role.profile['dimensions']['empathy'],'level':7}}}
        draft.side_effect=targeted;complete.return_value=workflow_fixtures.review_fixture(role);retrieve.reset_mock()
        self.act('regenerate',[role.pk]);job=PersonalityJob.objects.filter(character=role).latest('created_at')
        self.assertEqual(len(job.checkpoint['locked']),5)
        process_job(job.pk);role.refresh_from_db()
        self.assertEqual(requests,[['recovery']]);self.assertTrue(review_ready(role))
        self.assertEqual(role.profile['dimensions']['empathy']['level'],5)
        self.assertEqual(role.profile['dimensions']['recovery']['level'],6)
        retrieve.assert_not_called()

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_modified_proof_identity_or_score_invalidates_only_the_corresponding_lock(self,draft,complete,retrieve):
        role=self.partial(draft,complete,retrieve)
        role.profile['dimensions']['empathy']['level']=3
        self.assertEqual(len(retained_approvals(role)),4)
        role.refresh_from_db();role.source_text+='上下文新增了相反的明确行为。'
        self.assertEqual(retained_approvals(role),{})
        role.refresh_from_db();role.work_id+=1;self.assertEqual(retained_approvals(role),{})

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_three_rounds_are_available_when_new_evidence_keeps_arriving(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character(status='candidate')
        draft.side_effect=lambda *args:copy.deepcopy(role.profile);complete.return_value=workflow_fixtures.review_fixture(role,bad_key='recovery')
        def more(*args,**kwargs):
            return {'sources':[self.source(kwargs['round_number'])],'cache':{},'status':'added','queries':2,'fetched':1,'cached':0,'note':'新增测试来源'}
        retrieve.side_effect=more
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertEqual(role.profile_check['repair_rounds'],3);self.assertEqual(role.profile_check['stop_reason'],'budget_exhausted')
        self.assertEqual(role.profile_check['evidence']['queries'],6)
        self.assertEqual(draft.call_count,4);self.assertFalse(review_ready(role))

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_six_accepted_unchanged_dimensions_do_not_trigger_another_paid_generation(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character(status='candidate')
        draft.return_value=copy.deepcopy(role.profile);complete.return_value=workflow_fixtures.review_fixture(role)
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk)
        draft.reset_mock();complete.reset_mock();retrieve.reset_mock()
        self.act('regenerate',[role.pk]);process_job(PersonalityJob.objects.filter(character=role).latest('created_at').pk)
        role.refresh_from_db();self.assertTrue(review_ready(role))
        draft.assert_not_called();complete.assert_not_called();retrieve.assert_not_called()

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_failure_keeps_dimension_approvals_for_a_new_task(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character(status='candidate')
        draft.return_value=copy.deepcopy(role.profile);complete.return_value=workflow_fixtures.review_fixture(role,bad_key='recovery')
        retrieve.side_effect=ValueError('测试中断，来源与已认可内容须保留')
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertEqual(role.profile_check['status'],'error');self.assertEqual(len(retained_approvals(role)),5)
        self.act('regenerate',[role.pk]);job=PersonalityJob.objects.filter(character=role).latest('created_at')
        self.assertEqual(len(job.checkpoint['locked']),5)

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_five_valid_dimensions_are_reviewed_and_retained_even_when_one_has_no_score(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character(status='candidate')
        partial=copy.deepcopy(role.profile);partial['dimensions']['recovery']['level']=None
        draft.side_effect=lambda *args:copy.deepcopy(partial)
        complete.return_value=workflow_fixtures.review_fixture(role)
        retrieve.side_effect=self.empty
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertFalse(review_ready(role));self.assertEqual(len(retained_approvals(role)),5)
        self.assertIsNone(role.profile['dimensions']['recovery']['level'])
        self.assertEqual(role.profile_check['dimensions'][1]['verdict'],'insufficient')
        targets=[]
        def fix(row,*args):
            targets.append(row._revision_targets);return {'dimensions':{'recovery':role.profile['dimensions']['empathy']}}
        draft.side_effect=fix
        self.act('regenerate',[role.pk]);process_job(PersonalityJob.objects.filter(character=role).latest('created_at').pk);role.refresh_from_db()
        self.assertEqual(targets,[['recovery']]);self.assertTrue(review_ready(role))
        self.assertEqual(len(role.profile_check['reused_dimensions']),5)
