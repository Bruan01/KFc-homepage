import copy
from unittest.mock import patch

from django.test import TestCase

from . import tests as fixtures
from . import test_workflow as workflow_fixtures
from .catalog import validate_profile, profile_draft
from .character_rubric import RUBRIC, VERSION, evidence_inventory
from .models import Character, PersonalityJob, PersonalitySettings
from .review import review_profile, review_ready, source_fingerprint
from .services import process_job


class EvidenceFirstTests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp
    send=fixtures.PersonalityTests.send
    character=fixtures.PersonalityTests.character
    act=workflow_fixtures.WorkflowTests.act

    def unavailable(self,*args,**kwargs):
        return {'sources':[],'cache':{},'status':'empty','queries':0,'fetched':0,'cached':0,'note':'测试来源没有新网页，保留现有原文。'}

    def test_inventory_is_literal_and_does_not_assign_scores(self):
        role=self.character();table=evidence_inventory(role)
        self.assertEqual(table['version'],VERSION);self.assertEqual(len(table['dimensions']),6)
        self.assertEqual(table['scope']['work'],role.work_name)
        for row in table['dimensions'].values():
            self.assertNotIn('level',row)
            for item in row['candidates']:
                self.assertIn(item['quote'],role.source_text)

    @patch('apps.personality.catalog.complete_json')
    def test_generation_and_review_share_the_same_rubric(self,draft_call):
        role=self.character();draft_call.return_value=role.profile
        profile_draft(role,PersonalitySettings())
        generation=draft_call.call_args.args[2]
        calls=[]
        def review(config,prompt,payload):
            calls.append(payload);return workflow_fixtures.review_fixture(role)
        review_profile(role,role.profile,PersonalitySettings(),review)
        self.assertEqual(generation['rubric'],RUBRIC);self.assertEqual(calls[0]['rubric'],RUBRIC)
        self.assertEqual(generation['evidence_table'],calls[0]['evidence_table'])

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_ai_assigns_one_mbti_type_and_role_can_be_published(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate',mbti_type='')
        draft.return_value={**copy.deepcopy(role.profile),'mbti_type':'ENFJ'}
        complete.return_value=workflow_fixtures.review_fixture(role);retrieve.side_effect=self.unavailable
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertEqual(role.mbti_type,'ENFJ');self.assertNotIn('mbti_type',role.profile)
        self.assertTrue(review_ready(role));self.assertEqual(self.act('approve',[role.pk]).json()['changed'],1)

    @patch('apps.personality.workflow.mbti_draft',return_value='INTJ')
    def test_one_click_mbti_only_updates_missing_approved_roles_without_replacing_profiles(self,mbti):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='approved',mbti_type='')
        self.character(status='approved',mbti_type='INFP',name='已有类型')
        self.character(status='draft',mbti_type='',name='待发布角色')
        original=copy.deepcopy(role.profile);original_check=copy.deepcopy(role.profile_check);original_revision=role.revision
        response=self.send('/api/admin/personality/characters/batch-action',{'action':'complete_mbti'},self.admin)
        self.assertEqual(response.status_code,202,response.content);self.assertEqual(response.json()['queued'],1)
        job=PersonalityJob.objects.get(character=role)
        self.assertTrue(job.parameters['mbti_only']);self.assertEqual(PersonalityJob.objects.filter(kind='profile').count(),1)
        self.assertEqual(self.admin.get('/api/admin/personality/jobs').json()['mbti_active'],1)
        duplicate=self.send('/api/admin/personality/characters/batch-action',{'action':'complete_mbti'},self.admin).json()
        self.assertEqual(duplicate['queued'],0);self.assertEqual(len(duplicate['skipped']),1)
        process_job(job.pk);role.refresh_from_db();job.refresh_from_db()
        self.assertEqual(role.mbti_type,'INTJ');self.assertEqual(role.status,'approved')
        self.assertEqual(role.profile,original);self.assertEqual(role.profile_check,original_check)
        self.assertEqual(role.revision,original_revision+1);self.assertEqual(job.status,'completed')
        self.assertEqual(job.result['mbti_type'],'INTJ');mbti.assert_called_once()
        self.assertEqual(self.admin.get('/api/admin/personality/jobs').json()['mbti_active'],0)

    @patch('apps.personality.workflow.motto_draft',return_value='珍惜真实的连接，也慢慢学会向前。')
    def test_one_click_motto_only_updates_old_approved_roles_without_replacing_profile(self,motto):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='approved',name='旧角色');role.profile.pop('motto');role.save()
        self.character(status='approved',name='已有座右铭')
        quoted=self.character(status='approved',name='已有原话');quoted.profile.pop('motto');quoted.profile['signature_quote']={'text':'他会察觉他人的难处','source_url':quoted.source_url};quoted.save()
        draft=self.character(status='draft',name='待发布');draft.profile.pop('motto');draft.save()
        original=copy.deepcopy(role.profile);original_revision=role.revision
        role.profile_check={'status':'manual','summary':'保留原复核'};role.save()
        response=self.send('/api/admin/personality/characters/batch-action',{'action':'complete_mottos'},self.admin)
        self.assertEqual(response.status_code,202,response.content);self.assertEqual(response.json()['queued'],1)
        job=PersonalityJob.objects.get(character=role);self.assertTrue(job.parameters['motto_only'])
        self.assertEqual(self.admin.get('/api/admin/personality/jobs').json()['motto_active'],1)
        duplicate=self.send('/api/admin/personality/characters/batch-action',{'action':'complete_mottos'},self.admin).json()
        self.assertEqual(duplicate['queued'],0);self.assertEqual(len(duplicate['skipped']),1)
        process_job(job.pk);role.refresh_from_db();job.refresh_from_db()
        self.assertEqual(role.profile['motto'],'珍惜真实的连接，也慢慢学会向前。')
        self.assertEqual(role.profile['summary'],original['summary']);self.assertEqual(role.profile['dimensions'],original['dimensions'])
        self.assertEqual(role.status,'approved');self.assertEqual(role.profile_check['status'],'manual');self.assertEqual(role.profile_check['summary'],'保留原复核')
        self.assertEqual(role.revision,original_revision+1);self.assertEqual(job.status,'completed');motto.assert_called_once()
        self.assertEqual(self.admin.get('/api/admin/personality/jobs').json()['motto_active'],0)
        self.assertEqual(self.admin.get('/api/admin/personality/characters?status=approved').json()['missing_mottos'],0)

    @patch('apps.personality.workflow.mbti_draft')
    def test_failed_mbti_only_job_can_retry_without_marking_profile_review_failed(self,mbti):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='approved',mbti_type='');role.profile_check={'status':'manual','summary':'保留人工复核'}
        role.save();original_check=copy.deepcopy(role.profile_check)
        self.send('/api/admin/personality/characters/batch-action',{'action':'complete_mbti'},self.admin)
        job=PersonalityJob.objects.get(character=role);mbti.side_effect=ValueError('测试接口异常')
        process_job(job.pk);job.refresh_from_db();role.refresh_from_db()
        self.assertEqual(job.status,'failed');self.assertEqual(role.profile_check,original_check)
        retry=self.send(f'/api/admin/personality/jobs/{job.pk}/retry',{},self.admin)
        self.assertEqual(retry.status_code,202,retry.content);self.assertEqual(role.profile_check,original_check)
        mbti.side_effect=None;mbti.return_value='ENTP';process_job(job.pk);role.refresh_from_db()
        self.assertEqual(role.mbti_type,'ENTP');self.assertEqual(role.profile_check,original_check)

    @patch('apps.personality.catalog.complete_json')
    def test_existing_manual_mbti_is_not_requested_or_replaced(self,complete):
        role=self.character(mbti_type='INFP');complete.return_value=role.profile
        profile_draft(role,PersonalitySettings())
        prompt,payload=complete.call_args.args[1:]
        self.assertEqual(payload['current_mbti'],'INFP');self.assertNotIn('mbti_type',payload['output_schema'])
        self.assertIn('必须保留',prompt)

    @patch('apps.personality.profile_pipeline.evidence_connection',return_value=object())
    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_empty_inventory_is_supplemented_before_first_generation(self,draft,complete,retrieve,connection):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');events=[]
        retrieve.side_effect=lambda *a,**kw:(events.append('search') or self.unavailable())
        draft.side_effect=lambda *a,**kw:(events.append('draft') or copy.deepcopy(role.profile))
        complete.return_value=workflow_fixtures.review_fixture(role)
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk)
        self.assertEqual(events[:2],['search','draft']);role.refresh_from_db();self.assertTrue(review_ready(role))

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_two_targeted_repairs_keep_accepted_dimensions(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');profiles=[copy.deepcopy(role.profile) for _ in range(3)]
        profiles[1]['dimensions']['empathy']['level']=7
        profiles[1]['dimensions']['recovery']['level']=6
        profiles[2]['dimensions']['empathy']['level']=1
        profiles[2]['dimensions']['divergence']['level']=6
        # Targeted repairs may return just the patch; summary and other dimensions stay intact.
        profiles[2]={'dimensions':{'divergence':profiles[2]['dimensions']['divergence']}}
        targets=[]
        def generate(row,*args):
            targets.append(list(row._revision_targets));return profiles.pop(0)
        draft.side_effect=generate;retrieve.side_effect=self.unavailable
        checks=[workflow_fixtures.review_fixture(role,bad_key='recovery'),workflow_fixtures.review_fixture(role,bad_key='divergence'),workflow_fixtures.review_fixture(role)]
        checks[0]['dimensions'][4]['verdict']='insufficient'
        # Already accepted empathy must not fluctuate merely because another dimension is being repaired.
        checks[1]['dimensions'][2]['verdict']='insufficient'
        complete.side_effect=checks
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk);role.refresh_from_db()
        self.assertTrue(review_ready(role));self.assertEqual(targets[1],['recovery','divergence']);self.assertEqual(targets[2],['divergence'])
        self.assertEqual(role.profile['dimensions']['empathy']['level'],5)
        self.assertEqual(role.profile['dimensions']['recovery']['level'],6)
        self.assertEqual(role.profile['dimensions']['divergence']['level'],6)
        self.assertEqual(role.profile_check['repair_rounds'],2);self.assertEqual(retrieve.call_count,2)

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_unresolved_dimensions_stop_early_without_new_evidence_or_progress(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');partial=copy.deepcopy(role.profile)
        for key in ['recovery','empathy','boundary']:partial['dimensions'][key]['level']=None
        inference_calls=[]
        def generate(row,*args):
            inference_calls.append(list(getattr(row,'_inference_targets',[])));return copy.deepcopy(partial)
        draft.side_effect=generate
        complete.return_value=workflow_fixtures.review_fixture(role);retrieve.side_effect=self.unavailable
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertFalse(review_ready(role));self.assertEqual(role.status,'draft');self.assertEqual(draft.call_count,2)
        self.assertEqual(inference_calls,[[],[]]);self.assertEqual(role.profile_check['stop_reason'],'no_progress')
        self.assertEqual(self.act('approve',[role.pk]).json()['changed'],0)

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_two_missing_dimensions_are_inferred_marked_and_publishable(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');partial=copy.deepcopy(role.profile)
        for key in ['recovery','boundary']:partial['dimensions'][key]['level']=None
        def generate(row,*args):
            if getattr(row,'_inference_targets',[]):
                return {'dimensions':{key:{'level':4,'evidence_type':'inferred','reason':'现有资料只能支持保守推断，仍需管理员结合实际剧情复核。'} for key in row._inference_targets}}
            return copy.deepcopy(partial)
        draft.side_effect=generate;complete.return_value=workflow_fixtures.review_fixture(role);retrieve.side_effect=self.unavailable
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertTrue(review_ready(role));self.assertEqual(role.profile_check['status'],'passed')
        for key in ['recovery','boundary']:
            dimension=role.profile['dimensions'][key]
            self.assertEqual(dimension['evidence_type'],'inferred');self.assertNotIn('quote',dimension)
            self.assertEqual(next(item for item in role.profile_check['dimensions'] if item['key']==key)['verdict'],'inferred')
        from .catalog import evidence_summary
        self.assertEqual(evidence_summary(role.profile)['weights']['recovery'],0.5)
        self.assertEqual(len(evidence_summary(role.profile)['verified']),4)
        self.assertEqual(self.act('approve',[role.pk]).json()['changed'],1)
        role.refresh_from_db();self.assertEqual(role.status,'approved')

    @patch('apps.personality.catalog.complete_json')
    def test_inference_prompt_requires_explicit_type_and_no_source_quote(self,complete):
        role=self.character();role._revision_targets=['recovery'];role._inference_targets=['recovery']
        complete.return_value={'dimensions':{'recovery':{'level':4,'evidence_type':'inferred','reason':'这是缺少直接资料时的保守推断，仍需要人工结合实际剧情复核。'}}}
        profile=profile_draft(role,PersonalitySettings())
        payload=complete.call_args.args[2]
        self.assertEqual(payload['inference_targets'],['recovery'])
        self.assertEqual(payload['output_schema']['dimensions']['recovery']['evidence_type'],'inferred')
        self.assertIn('不要提供 evidence_id、quote',complete.call_args.args[1])
        self.assertEqual(profile['dimensions']['recovery']['evidence_type'],'inferred')

    def test_inferred_dimension_with_explicit_contradiction_still_fails_review(self):
        role=self.character();role.profile['dimensions']['recovery']={'level':4,'evidence_type':'inferred','reason':'这是保守推断，但当前资料存在明确的相反行为，需要继续核对。'}
        result=workflow_fixtures.review_fixture(role)
        result['dimensions'][1].update(verdict='contradicted',source_quote='他会察觉他人的难处')
        check=review_profile(role,role.profile,PersonalitySettings(),lambda *args:result)
        self.assertEqual(check['status'],'needs_sources');self.assertTrue(check['issues'])

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_review_only_does_not_generate_or_search(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character(status='draft')
        complete.return_value=workflow_fixtures.review_fixture(role)
        self.act('recheck',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk)
        draft.assert_not_called();retrieve.assert_not_called();role.refresh_from_db();self.assertTrue(review_ready(role))

    def test_additional_quotes_are_checked_literally(self):
        role=self.character();role.profile['dimensions']['empathy']['supporting_quotes']=['这段话并不在原始资料中存在']
        with self.assertRaises(ValueError):validate_profile(role.profile,role)

    def test_contradiction_requires_a_literal_counterexample(self):
        role=self.character();check=workflow_fixtures.review_fixture(role)
        check['dimensions'][0].update(verdict='contradicted',source_quote='不存在于原文中的所谓相反事实')
        with self.assertRaises(ValueError):review_profile(role,role.profile,PersonalitySettings(),lambda *args:check)

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_explicit_contradiction_can_reopen_a_previously_accepted_dimension(self,draft,complete,retrieve):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character(status='candidate')
        proposals=[copy.deepcopy(role.profile) for _ in range(3)];proposals[2]['dimensions']['empathy']['level']=3
        draft.side_effect=proposals;retrieve.side_effect=self.unavailable
        first=workflow_fixtures.review_fixture(role,bad_key='recovery');second=workflow_fixtures.review_fixture(role,bad_key='empathy')
        second['dimensions'][2]['verdict']='contradicted'
        complete.side_effect=[first,second,workflow_fixtures.review_fixture(role)]
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertTrue(review_ready(role));self.assertEqual(role.profile['dimensions']['empathy']['level'],3)

    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_failed_legacy_task_upgrades_and_keeps_its_generated_draft(self,draft,complete):
        PersonalitySettings.objects.create(ai_enabled=True);role=self.character(status='draft')
        job=PersonalityJob.objects.create(kind='profile',character=role,status='failed',requested_by='root',parameters={'revision':role.revision},
            checkpoint={'source':source_fingerprint(role),'draft':role.profile})
        complete.return_value=workflow_fixtures.review_fixture(role)
        self.assertEqual(self.send(f'/api/admin/personality/jobs/{job.pk}/retry',client=self.admin).status_code,202)
        job.refresh_from_db();self.assertEqual(job.parameters['pipeline'],VERSION)
        process_job(job.pk);role.refresh_from_db();self.assertTrue(review_ready(role));draft.assert_not_called()
