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
        role=self.character(status='candidate');draft.side_effect=lambda *a:copy.deepcopy(role.profile)
        complete.return_value=workflow_fixtures.review_fixture(role,bad_key='recovery');retrieve.side_effect=self.unavailable
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertFalse(review_ready(role));self.assertEqual(role.status,'draft');self.assertEqual(draft.call_count,2)
        self.assertEqual(role.profile_check['stop_reason'],'no_progress')
        self.assertEqual(self.act('approve',[role.pk]).json()['changed'],0)

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
