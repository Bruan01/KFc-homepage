import copy
import io
import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import TestCase
from . import tests as fixtures
from .catalog import import_characters
from .models import Character, CharacterDiscovery, CharacterWorkScan, PersonalityJob, PersonalitySettings
from .questions import DIMENSIONS
from .review import profile_fingerprint, review_ready
from .services import process_job
from .transfer import export_catalog, import_catalog


def review_fixture(role, *, bad_key=None):
    return {"identity": {"verdict": "supported", "reason": "资料中的人物关系与作品身份一致。"},
        "dimensions": [{"key": key, "verdict": "insufficient" if key == bad_key else "supported", "reason": "这段行为记录支持该维度的限定情境解读。", "source_quote": role.profile["dimensions"][key]["quote"]} for key in DIMENSIONS],
        "summary": "各项解释有对应资料依据，可提交管理员决定是否发布。"}


class WorkflowTests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp
    send=fixtures.PersonalityTests.send
    character=fixtures.PersonalityTests.character

    def act(self, action, ids, **extra):
        return self.send('/api/admin/personality/characters/batch-action', {'action':action,'ids':ids,**extra}, self.admin)

    def approve_check(self, role):
        role.status='draft';role.profile_check={'status':'passed','fingerprint':profile_fingerprint(role),'issues':[],'summary':'已完成来源依据复核'};role.save()

    def test_default_queue_only_new_candidates_and_never_duplicates_jobs(self):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate')
        self.assertEqual(self.act('generate',[role.pk,role.pk]).json()['queued'],1)
        role.refresh_from_db();self.assertEqual(role.status,'draft');self.assertEqual(role.profile_check['status'],'queued')
        self.assertEqual(self.act('generate',[role.pk]).json()['queued'],0)
        self.assertEqual(PersonalityJob.objects.filter(character=role).count(),1)
        self.assertEqual(self.send('/api/admin/personality/characters/batch-action',{'action':'exclude','ids':[role.pk]}).status_code,401)

    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_generation_review_and_publish_are_distinct_steps(self, draft, complete):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');draft.return_value=copy.deepcopy(role.profile);complete.return_value=review_fixture(role)
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk)
        role.refresh_from_db();job.refresh_from_db()
        self.assertEqual(role.status,'draft');self.assertTrue(review_ready(role));self.assertEqual(job.status,'completed')
        draft.assert_called_once();complete.assert_called_once()
        response=self.act('approve',[role.pk],versions={str(role.pk):role.revision}).json()
        self.assertEqual(response['changed'],1);role.refresh_from_db();self.assertEqual(role.status,'approved');self.assertEqual(role.reviewed_by,'root')

    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_negative_ai_review_cannot_publish(self, draft, complete):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');draft.return_value=copy.deepcopy(role.profile);complete.return_value=review_fixture(role,bad_key='recovery')
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk)
        role.refresh_from_db();self.assertEqual(role.profile_check['status'],'needs_sources')
        response=self.act('approve',[role.pk]).json();self.assertEqual(response['changed'],0);self.assertTrue(response['skipped'])
        self.assertEqual(Character.objects.get(pk=role.pk).status,'draft')

    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_failed_review_resumes_draft_without_regenerating(self, draft, complete):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');draft.return_value=copy.deepcopy(role.profile);complete.side_effect=ValueError('复核连接暂不可用')
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk);job.refresh_from_db()
        self.assertEqual(job.status,'failed');self.assertIn('draft',job.checkpoint)
        complete.side_effect=None;complete.return_value=review_fixture(role)
        retry=self.send(f'/api/admin/personality/jobs/{job.pk}/retry',client=self.admin);self.assertEqual(retry.status_code,202)
        process_job(job.pk);job.refresh_from_db();role.refresh_from_db()
        self.assertEqual(job.status,'completed');self.assertTrue(review_ready(role));self.assertEqual(draft.call_count,1)

    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_source_change_during_review_cannot_publish_stale_result(self, draft, complete):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');draft.return_value=copy.deepcopy(role.profile)
        def change(*args):
            current=Character.objects.get(pk=role.pk);current.source_text+='这是管理员新补充并修正的资料。';current.revision+=1;current.profile_check={};current.save()
            return review_fixture(role)
        complete.side_effect=change
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk)
        role.refresh_from_db();job.refresh_from_db();self.assertEqual(job.status,'failed');self.assertEqual(role.profile_check,{})
        self.assertIn('管理员新补充',role.source_text)

    def test_bulk_partial_success_stale_version_and_hold_persist(self):
        one=self.character(status='draft');self.approve_check(one)
        two=self.character(status='draft');two.profile={};two.save()
        stale=self.act('approve',[one.pk],versions={str(one.pk):one.revision+1}).json();self.assertEqual(stale['changed'],0)
        self.act('hold',[one.pk]);one.refresh_from_db();self.assertTrue(one.profile_check['held']);self.assertTrue(review_ready(one))
        listed=self.admin.get('/api/admin/personality/characters?status=draft').json()['items']
        self.assertTrue(next(c for c in listed if c['id']==one.pk)['publication']['held'])
        result=self.act('approve',[one.pk,two.pk]).json();self.assertEqual(result['changed'],1);self.assertEqual(len(result['skipped']),1)
        self.assertEqual(Character.objects.get(pk=two.pk).status,'draft')

    def test_exclusion_and_restoration_preserve_profile_and_identity(self):
        role=self.character(status='candidate');original=copy.deepcopy(role.profile)
        self.act('exclude',[role.pk]);role.refresh_from_db();self.assertEqual(role.status,'excluded')
        self.act('restore',[role.pk]);role.refresh_from_db();self.assertEqual(role.status,'draft');self.assertEqual(role.profile,original)

    def test_classic_retention_is_explicit_in_initial_selection(self):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate',work_year=1990,classic_candidate=True,classic=False)
        self.act('generate',[role.pk],keep_classics=True);role.refresh_from_db();self.assertTrue(role.classic)

    def test_identity_mismatch_and_fabricated_review_quote_are_blocked(self):
        from .review import review_profile
        role=self.character(status='draft');settings=PersonalitySettings()
        result=review_fixture(role);result['identity']['verdict']='mismatch'
        check=review_profile(role,role.profile,settings,lambda *args:result);self.assertEqual(check['status'],'needs_sources')
        result=review_fixture(role);result['dimensions'][0]['source_quote']='这是来源中并不存在的虚构剧情'
        with self.assertRaises(ValueError):review_profile(role,role.profile,settings,lambda *args:result)

    def test_real_http_generation_and_review_pipeline(self):
        role=self.character(status='candidate');responses=[copy.deepcopy(role.profile),review_fixture(role)];paths=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));paths.append(self.path)
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'choices':[{'message':{'content':json.dumps(responses.pop(0))}}]}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        PersonalitySettings.objects.create(ai_enabled=True,base_url=f'http://127.0.0.1:{server.server_port}/v1',model='fixture')
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk)
        role.refresh_from_db();self.assertTrue(review_ready(role));self.assertEqual(paths,['/v1/chat/completions']*2)


class DiscoveryTests(TestCase):
    def setUp(self):
        PersonalitySettings.objects.create(min_work_collects=1,min_character_collects=1,per_work_limit=1)

    @staticmethod
    def work(pk):return {'id':pk,'name':f'作品{pk}','type':2,'date':f'{date.today().year}-01-01','collection':{'collect':100}}
    @staticmethod
    def detail(pk,summary=None):return {'id':pk,'name':f'人物{pk}','summary':summary if summary is not None else '这是一段足够长的真实来源测试夹具，描述角色在不同情境中的行为和关系，用于验证采集与去重，不用作正式人物数据。','stat':{'collects':100},'images':{'large':'https://lain.bgm.tv/pic/cover/l/fixture.jpg'}}

    @patch('apps.personality.catalog.time.sleep')
    @patch('apps.personality.catalog.bangumi')
    def test_source_ids_not_refetched_across_runs_or_different_works(self,fetch,sleep):
        calls=[]
        def answer(path,data=None):
            calls.append(path)
            if path.startswith('subjects/') and not path.endswith('/characters'):return self.work(int(path.split('/')[1]))
            if path.endswith('/characters'):return [{'id':101,'type':1,'relation':'主角'},{'id':102,'type':1,'relation':'配角'}]
            return self.detail(int(path.split('/')[1]),'太短' if path.endswith('/102') else None)
        fetch.side_effect=answer
        import_characters({'subject_ids':[1],'work_limit':1,'character_limit':10})
        # Existing characters no longer use up a work's new-character quota.
        import_characters({'subject_ids':[1],'work_limit':1,'character_limit':10})
        import_characters({'subject_ids':[2],'work_limit':1,'character_limit':10})
        self.assertEqual(calls.count('characters/101'),1);self.assertEqual(calls.count('characters/102'),1)
        self.assertEqual(Character.objects.count(),1);self.assertEqual(CharacterDiscovery.objects.get(source_id=102).outcome,'filtered')
        Character.objects.update(status='excluded');import_characters({'subject_ids':[1]});self.assertEqual(calls.count('characters/101'),1)

    @patch('apps.personality.catalog.time.sleep')
    @patch('apps.personality.catalog.bangumi')
    def test_pagination_moves_beyond_previously_scanned_works(self,fetch,sleep):
        calls=[]
        def answer(path,data=None):
            calls.append(path)
            if path.startswith('search/'):
                return {'data':[self.work(i) for i in range(1,21)] if 'offset=0' in path else [self.work(21)]}
            if path.endswith('/characters'):
                pk=int(path.split('/')[1]);return [{'id':1000+pk,'type':1,'relation':'主角'}]
            return self.detail(int(path.split('/')[1]))
        fetch.side_effect=answer
        first=import_characters({'work_limit':20,'character_limit':100});self.assertEqual(first['imported'],20)
        second=import_characters({'work_limit':1,'character_limit':10});self.assertEqual(second['imported'],1)
        self.assertTrue(any('offset=20' in call for call in calls));self.assertEqual(calls.count('characters/1001'),1)

    @patch('apps.personality.catalog.time.sleep')
    @patch('apps.personality.catalog.bangumi')
    def test_failed_detail_requires_explicit_retry(self,fetch,sleep):
        attempts=[]
        def answer(path,data=None):
            if path=='subjects/1':return self.work(1)
            if path.endswith('/characters'):return [{'id':300,'type':1,'relation':'主角'}]
            attempts.append(path)
            if len(attempts)==1:raise ValueError('连接超时')
            return self.detail(300)
        fetch.side_effect=answer
        params={'subject_ids':[1],'work_limit':1}
        import_characters(params);import_characters(params);self.assertEqual(len(attempts),1)
        import_characters({**params,'retry_errors':True});self.assertEqual(len(attempts),2);self.assertTrue(Character.objects.filter(source_id=300).exists())

    def test_filtered_ledger_survives_catalog_transfer_without_any_characters(self):
        CharacterDiscovery.objects.create(source_id=900,work_id=10,outcome='filtered',reason='简介不足')
        payload=export_catalog();CharacterDiscovery.objects.all().delete()
        import_catalog(payload);self.assertEqual(CharacterDiscovery.objects.get(source_id=900).outcome,'filtered')
