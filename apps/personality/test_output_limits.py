import copy
from unittest.mock import patch

from django.test import SimpleTestCase

from .models import PersonalitySettings
from .provider import AnalysisUnavailable,complete_json


def response(reason='stop',content='{"ok":true}'):
    return {'choices':[{'finish_reason':reason,'message':{'content':content}}]}


class OutputLimitTests(SimpleTestCase):
    def setUp(self):
        self.settings=PersonalitySettings(ai_enabled=True,base_url='https://api.deepseek.com/v1',model='deepseek-flash',max_output_tokens=8000)

    @patch('apps.personality.provider._request')
    def test_role_truncation_has_one_compact_retry_without_raising_the_budget(self,request):
        bodies=[]
        def answer(config,path,body):
            bodies.append(copy.deepcopy(body))
            return response('length','{"part":') if len(bodies)==1 else response()
        request.side_effect=answer
        self.assertEqual(complete_json(self.settings,'角色结构化分析',{'purpose':'character_profile'}),{'ok':True})
        self.assertEqual(request.call_count,2)
        self.assertEqual(bodies[0]['reasoning_effort'],'low')
        self.assertEqual(bodies[1]['thinking'],{'type':'disabled'})
        self.assertEqual([body['max_tokens'] for body in bodies],[8000,8000])
        self.assertNotIn('reasoning_effort',bodies[1])

    @patch('apps.personality.provider._request',return_value=response('length'))
    def test_second_truncation_stops_and_returns_actionable_error(self,request):
        with self.assertRaisesRegex(AnalysisUnavailable,'输出被截断.*8000'):
            complete_json(self.settings,'角色结构化分析',{'purpose':'character_review'})
        self.assertEqual(request.call_count,2)

    @patch('apps.personality.provider._request',return_value=response())
    def test_general_report_requests_keep_the_provider_default(self,request):
        complete_json(self.settings,'用户报告',{'answers':[]})
        body=request.call_args.args[2]
        self.assertNotIn('thinking',body);self.assertNotIn('response_format',body)

    @patch('apps.personality.provider._request',return_value=response('length'))
    def test_other_gateways_do_not_receive_vendor_specific_parameters(self,request):
        self.settings.base_url='https://proxy.example/v1'
        with self.assertRaises(AnalysisUnavailable):complete_json(self.settings,'角色结构化分析',{'purpose':'character_profile'})
        self.assertEqual(request.call_count,1)
        self.assertNotIn('thinking',request.call_args.args[2])
