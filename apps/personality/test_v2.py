import copy
import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from . import tests as fixtures
from .models import Assessment, Character, PersonalityJob, PersonalitySettings
from .questions import AXES, DIMENSIONS, initial_steps, interview_step
from .services import build_report, process_job
from .transfer import export_catalog, import_catalog


class ExplorationV2Tests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    create = fixtures.PersonalityTests.create
    finish = fixtures.PersonalityTests.finish
    character = fixtures.PersonalityTests.character

    def test_stratified_variation_retains_scoring_and_resume_snapshot(self):
        one = initial_steps(seed="one")
        self.assertEqual(one, initial_steps(seed="one"))
        ids = {q["id"] for s in one for q in s["questions"]}
        second = initial_steps(seed="two", previous_ids=ids)
        second_ids = {q["id"] for s in second for q in s["questions"]}
        self.assertLess(len(ids & second_ids), 18)
        for target in [*AXES, *DIMENSIONS]:
            items = [q for step in second for q in step["questions"] if q.get("target") == target]
            self.assertEqual(len(items), 6 if target in AXES else 4)
            self.assertTrue(any(q["reverse"] for q in items)); self.assertTrue(any(not q["reverse"] for q in items))
        a = self.create(); b = self.create()
        self.assertNotEqual(a["step"]["questions"], b["step"]["questions"])
        persisted = self.client.get('/api/personality/assessments/'+a['id']).json()
        self.assertEqual(persisted['step'], a['step'])

    def test_interview_is_selected_by_answers_not_just_shuffled(self):
        steps = initial_steps(seed="branches")
        high = {q['id']: {'value': 1 if q['reverse'] else 7} for s in steps for q in s['questions'] if q['kind']=='scale'}
        low = {q['id']: {'value': 7 if q['reverse'] else 1} for s in steps for q in s['questions'] if q['kind']=='scale'}
        a = interview_step(steps, high, seed="same")['questions']
        b = interview_step(steps, low, seed="same")['questions']
        self.assertTrue(all(q['branch']=='high' for q in a)); self.assertTrue(all(q['branch']=='low' for q in b))
        self.assertTrue(all(x['text'] != y['text'] for x,y in zip(a,b)))

    def test_backtracking_does_not_rebind_existing_open_answers_to_new_prompts(self):
        from .services import advance
        row=self.finish(context=True)
        saved=copy.deepcopy(row.steps[7:]);answers=copy.deepcopy(row.answers)
        row.step_index=5;row.status='active'
        for answer in row.answers.values():
            if answer.get('value') is not None: answer['value']=8-answer['value']
        advance(row)
        self.assertEqual(row.steps[7:],saved)
        for qid,answer in answers.items():
            if qid.startswith(('open-','follow-')): self.assertEqual(row.answers[qid],answer)

    def test_model_and_crawler_pages_and_saves_are_separate(self):
        def read_page(path):
            response = self.admin.get(path)
            self.addCleanup(response.close)
            return (b''.join(response.streaming_content) if response.streaming else response.content).decode()
        catalog = read_page('/admin/personality')
        models = read_page('/admin/personality/settings')
        self.assertNotIn('name="api_key"', catalog)
        self.assertNotIn('name="recent_years"', models)
        self.assertIn('name="api_key"', models)
        PersonalitySettings.objects.create(model='kept-model', min_work_collects=2000)
        response = self.send('/api/admin/personality/catalog-settings', {'min_work_collects': 3500}, self.admin)
        self.assertEqual(response.status_code,200)
        row = PersonalitySettings.objects.get(pk=1); self.assertEqual(row.model,'kept-model'); self.assertEqual(row.min_work_collects,3500)
        self.assertEqual(self.send('/api/admin/personality/catalog-settings', {'model':'wrong'}, self.admin).status_code,400)
        self.assertNotIn('model', self.admin.get('/api/admin/personality/catalog-settings').json()['settings'])

    def test_catalog_roundtrip_excludes_secrets_and_preserves_reviewed_conflicts(self):
        role = self.character()
        row = self.finish()
        PersonalitySettings.objects.create(api_key_ciphertext='sensitive-ciphertext')
        payload = export_catalog(); encoded = json.dumps(payload)
        self.assertNotIn('sensitive-ciphertext',encoded); self.assertNotIn(str(row.pk),encoded); self.assertNotIn('answers',payload)
        changed = copy.deepcopy(payload); changed['characters'][0]['name']='不应覆盖已有审核'
        self.assertEqual(import_catalog(changed)['preserved'],1)
        role.refresh_from_db(); self.assertNotEqual(role.name,'不应覆盖已有审核')
        Character.objects.all().delete()  # Isolated Django test database only.
        self.assertEqual(import_catalog(payload)['imported'],1)
        restored = Character.objects.get(source_id=role.source_id)
        from .catalog import validate_profile
        self.assertEqual(restored.status,'approved'); self.assertEqual(restored.profile,validate_profile(role.profile,role))

    def test_invalid_catalog_is_rejected_before_writing_any_rows(self):
        self.character()
        payload = export_catalog()
        second = copy.deepcopy(payload['characters'][0]); second['source_id']=500;second['name']='无效资料'
        second['profile']['dimensions']['empathy']['quote']='这段引文没有存在于任何来源'
        payload['characters'].append(second)
        with self.assertRaises(ValueError): import_catalog(payload)
        self.assertEqual(Character.objects.count(),1)
        payload = export_catalog(); payload['characters'][0]['api_key']='forged'
        self.assertEqual(self.send('/api/admin/personality/catalog/import',payload,self.admin).status_code,400)
        self.assertEqual(self.client.get('/api/admin/personality/catalog/export').status_code,401)

    def test_starter_has_real_images_evidence_and_is_idempotent(self):
        call_command('seed_personality_catalog', stdout=io.StringIO())
        self.assertEqual(Character.objects.filter(status='approved').count(),5)
        first = Character.objects.get(source_id=2162)
        self.assertEqual(first.theme,'sunshine'); self.assertTrue(first.image_url.startswith('https://lain.bgm.tv/'))
        first.status='excluded';first.save()
        call_command('seed_personality_catalog', stdout=io.StringIO())
        first.refresh_from_db();self.assertEqual(first.status,'excluded');self.assertEqual(Character.objects.count(),5)
        public=self.client.get('/api/personality/config').json()
        self.assertEqual(public['characters_ready'],4)
        self.assertNotIn(first.pk,[item['id'] for item in public['cast']])
        self.assertEqual(self.client.get(f'/api/personality/cast/{first.pk}/image').status_code,404)

    @patch('apps.personality.services.complete_json')
    def test_old_report_can_add_character_once_without_repeating_test_or_changing_answers(self, complete):
        row = self.finish(); row.report=build_report(row);row.status='completed';row.save()
        before=copy.deepcopy(row.report);answers=copy.deepcopy(row.answers)
        self.assertIsNone(before['character'])
        self.character()
        endpoint=f'/api/personality/assessments/{row.pk}/complete-character'
        self.assertEqual(self.send(endpoint).status_code,202)
        self.assertEqual(self.send(endpoint).status_code,202)
        job=PersonalityJob.objects.get(assessment=row);process_job(job.pk)
        row.refresh_from_db()
        for field in ['type','axes','dimensions','quote','sections','growth']:
            self.assertEqual(row.report[field],before[field])
        self.assertEqual(row.answers,answers);self.assertIsNotNone(row.report['character'])
        self.assertEqual(self.send(endpoint).status_code,200)
        self.assertEqual(PersonalityJob.objects.filter(assessment=row).count(),1)
        complete.assert_not_called()
