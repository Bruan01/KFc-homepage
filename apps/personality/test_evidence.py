import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase

from .catalog import normalize_draft
from .evidence import evidence_connection, public_url, supplement, source_key
from .models import Character, PersonalityJob, PersonalitySettings
from .provider import AnalysisUnavailable
from .provider import _request as provider_request, encrypt_key
from .review import review_ready
from .services import process_job
from . import tests as fixtures
from . import test_workflow as workflow_fixtures

review_fixture = workflow_fixtures.review_fixture


class EvidenceSourceTests(SimpleTestCase):
    def setUp(self):
        self.settings = PersonalitySettings(base_url='https://api.deepseek.com/v1', api_key_ciphertext='test-cipher')
        self.role = Character(source_id=12, name='人物甲', work_id=1, work_name='测试作品', source_url='https://bgm.tv/character/12')
        self.text = '人物甲在测试作品中经历了失落，向伙伴说明自己的需要，重新整理心情并继续行动。'*5

    def test_credentials_are_only_reused_for_the_official_host(self):
        self.assertEqual(evidence_connection(self.settings).base_url, 'https://api.deepseek.com/v1')
        for url in ['https://api.deepseek.com.evil.example/v1', 'http://api.deepseek.com/v1', 'https://other.example/v1']:
            self.settings.base_url=url
            self.assertIsNone(evidence_connection(self.settings))
        self.settings.evidence_api_key_ciphertext='independent-cipher'
        self.assertEqual(evidence_connection(self.settings).api_key_ciphertext,'independent-cipher')

    def test_private_and_invalid_urls_are_rejected(self):
        for url in ['http://example.com/page','https://127.0.0.1/test','https://10.0.0.1/','https://localhost/x','https://host.internal/x','https://user:pw@example.com/x','https://example.com:8443/x']:
            self.assertEqual(public_url(url),'')
        self.assertEqual(source_key('https://baike.baidu.com/item/人物甲/123?fromModule=foo'), source_key('https://wapbaike.baidu.com/item/人物甲/123?bst=tracking'))

    @patch('apps.personality.evidence._request')
    def test_fetches_actual_content_not_search_summary_and_caches(self, request):
        def respond(config,path,body):
            if path=='/tools/search':
                return {'results':[{'url':'https://zh.wikipedia.org/wiki/test','title':'人物甲 测试作品','authority':3,'summary':'这不是可引用的网页正文','content':''}]}
            self.assertEqual(path,'/tools/fetch')
            return {'content':self.text}
        request.side_effect=respond
        first=supplement(self.role,self.settings,['recovery'])
        self.assertEqual(first['sources'][0]['text'],self.text)
        self.assertNotIn('这不是可引用',first['sources'][0]['text'])
        self.assertLessEqual(first['queries'],2);self.assertLessEqual(first['fetched'],3)
        self.role.evidence_cache=first['cache']
        count=request.call_count
        second=supplement(self.role,self.settings,['recovery'])
        self.assertEqual(request.call_count,count)
        self.assertTrue(second['cached'])
        self.assertEqual(second['sources'],first['sources'])

    @patch('apps.personality.evidence._request')
    def test_rejects_wrong_identity_and_personality_labels(self, request):
        request.return_value={'results':[
            {'url':'https://zh.wikipedia.org/wiki/wrong','authority':3,'title':'另一位角色','content':self.text.replace('人物甲','人物乙')},
            {'url':'https://example.com/mbti','authority':3,'title':'人物甲 MBTI','content':self.text},
            {'url':'https://random.example/blog','authority':0,'title':'人物甲','content':self.text},
        ]}
        result=supplement(self.role,self.settings,['recovery'])
        self.assertEqual(result['sources'],[])
        self.assertEqual(result['status'],'empty')

    @patch('apps.personality.evidence._request', side_effect=AnalysisUnavailable('搜索服务鉴权失败'))
    def test_error_cache_avoids_repeated_paid_requests(self, request):
        first=supplement(self.role,self.settings,['recovery']);self.role.evidence_cache=first['cache']
        count=request.call_count
        second=supplement(self.role,self.settings,['recovery'])
        self.assertEqual(request.call_count,count)
        self.assertEqual(second['status'],'error')
        self.assertIn('鉴权失败',second['note'])

    @patch('apps.personality.evidence._request')
    def test_mobile_mirrors_and_copied_text_do_not_count_as_new_sources(self, request):
        request.return_value={'results':[
            {'url':'https://baike.baidu.com/item/人物甲/123?fromModule=a','authority':3,'title':'人物甲 测试作品','content':self.text},
            {'url':'https://wapbaike.baidu.com/item/人物甲/123?fromModule=b','authority':3,'title':'人物甲 测试作品','content':self.text},
            {'url':'https://baike.baidu.com/item/人物甲/456','authority':3,'title':'人物甲 测试作品','content':self.text},
            {'url':'https://zh.wikipedia.org/wiki/copied','authority':3,'title':'人物甲 测试作品','content':self.text},
        ]}
        result=supplement(self.role,self.settings,['recovery'])
        self.assertEqual(len(result['sources']),1)
        self.assertEqual(result['fetched'],0)
        queries=[call.args[2]['query'] for call in request.call_args_list if call.args[1]=='/tools/search']
        self.assertTrue(all('受挫后恢复振作' in query for query in queries))
        self.assertTrue(all('-site:baike.baidu.com' not in query for query in queries))

    def test_old_structured_mechanism_is_text_without_filled_scores(self):
        original={'mechanism':{'价值':['原有文本内容保持不变'],'关系':None},'dimensions':{'recovery':{'level':None}}}
        result=normalize_draft(original)
        self.assertEqual(result['mechanism'],'价值：原有文本内容保持不变')
        self.assertIsNone(result['dimensions']['recovery']['level'])
        self.assertIsInstance(original['mechanism'],dict)

    def test_search_and_fetch_transport_over_real_http(self):
        paths=[];text=self.text
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));paths.append((self.path,payload))
                data={'results':[{'url':'https://zh.wikipedia.org/wiki/test','authority':3,'title':'人物甲 测试作品'}]} if self.path.endswith('/search') else {'content':text}
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(data).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        self.settings.api_key_ciphertext=encrypt_key('http-fixture-key')
        def local_transport(config,path,body):
            config=copy.copy(config);config.base_url=f'http://127.0.0.1:{server.server_port}/v1'
            return provider_request(config,path,body)
        with patch('apps.personality.evidence._request',side_effect=local_transport):
            result=supplement(self.role,self.settings,['recovery'])
        self.assertEqual(result['sources'][0]['text'],text)
        self.assertTrue(any(path=='/v1/tools/search' for path,body in paths))
        self.assertTrue(any(path=='/v1/tools/fetch' for path,body in paths))
        self.assertTrue(all(body.get('need_content') is True for path,body in paths if path.endswith('/search')))


class EvidencePipelineTests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp
    send=fixtures.PersonalityTests.send
    character=fixtures.PersonalityTests.character
    act=workflow_fixtures.WorkflowTests.act

    def source_result(self):
        return {'sources':[{'url':'https://zh.wikipedia.org/wiki/source','text':'这是隔离测试的新增来源，描述角色从挫折中慢慢恢复并重建自己的生活。'}],
                'cache':{},'status':'added','queries':1,'fetched':1,'cached':0,'note':'已补充一个来源。'}

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_missing_evidence_is_enriched_regenerated_and_reviewed(self,draft,complete,search):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');complete_profile=copy.deepcopy(role.profile)
        incomplete=copy.deepcopy(role.profile);incomplete['mechanism']={'说明':incomplete['mechanism']};incomplete['dimensions']['recovery']['level']=None
        draft.side_effect=[incomplete,complete_profile];complete.return_value=review_fixture(role);search.return_value=self.source_result()
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk)
        role.refresh_from_db();job.refresh_from_db()
        self.assertTrue(review_ready(role));self.assertEqual(role.status,'draft')
        self.assertEqual(len(role.extra_sources),1);self.assertEqual(role.profile_check['evidence']['added'],1)
        self.assertEqual(draft.call_count,2);self.assertEqual(complete.call_count,2);self.assertEqual(search.call_count,1)
        self.assertEqual(job.status,'completed');self.assertEqual(job.checkpoint,{})

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_review_retry_preserves_new_sources_without_redrafting_or_research(self,draft,complete,search):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');full=copy.deepcopy(role.profile);partial=copy.deepcopy(full);partial['dimensions']['recovery']['level']=None
        draft.side_effect=[partial,full];search.return_value=self.source_result()
        complete.side_effect=[review_fixture(role,bad_key='recovery'),ValueError('复核调用暂不可用')]
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk);job.refresh_from_db()
        self.assertEqual(job.status,'failed');self.assertTrue(job.checkpoint['evidence_attempted'])
        complete.side_effect=None;complete.return_value=review_fixture(role)
        self.assertEqual(self.send(f'/api/admin/personality/jobs/{job.pk}/retry',client=self.admin).status_code,202)
        process_job(job.pk);role.refresh_from_db()
        self.assertTrue(review_ready(role));self.assertEqual(draft.call_count,2);self.assertEqual(search.call_count,1)

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.complete_json')
    @patch('apps.personality.services.profile_draft')
    def test_administrator_edit_during_search_is_not_overwritten(self,draft,complete,search):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');profile=copy.deepcopy(role.profile);profile['dimensions']['recovery']['level']=None;draft.return_value=profile
        complete.return_value=review_fixture(role,bad_key='recovery')
        def edit(*args,**kwargs):
            Character.objects.filter(pk=role.pk).update(revision=10,extra_sources=[{'url':'https://example.com/human','text':'管理员新保存的原文资料不能被旧搜索任务覆盖。'}])
            return self.source_result()
        search.side_effect=edit
        self.act('generate',[role.pk]);job=PersonalityJob.objects.get(character=role);process_job(job.pk);role.refresh_from_db();job.refresh_from_db()
        self.assertEqual(job.status,'failed');self.assertEqual(role.revision,10)
        self.assertEqual(role.extra_sources[0]['url'],'https://example.com/human')

    @patch('apps.personality.workflow.supplement')
    @patch('apps.personality.services.profile_draft')
    def test_bad_shape_is_not_mislabelled_as_evidence_shortage(self,draft,search):
        PersonalitySettings.objects.create(ai_enabled=True)
        role=self.character(status='candidate');draft.return_value={'summary':'过短','mechanism':'过短','dimensions':{}}
        self.act('generate',[role.pk]);process_job(PersonalityJob.objects.get(character=role).pk);role.refresh_from_db()
        self.assertEqual(role.profile_check['category'],'format_error');search.assert_not_called()
