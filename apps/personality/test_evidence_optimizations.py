import copy
from unittest.mock import patch

from django.test import SimpleTestCase,TestCase,Client

from . import tests as fixtures
from .catalog import profile_draft,validate_profile
from .character_rubric import evidence_inventory,evidence_registry,resolve_profile_references
from .evidence import supplement,query_plan,duplicate_text,focus_document
from .identity import metadata_identity,hydrate_identity,identity_matches,contains_alias
from .models import Character,PersonalitySettings
from .review import review_profile,profile_fingerprint,review_ready


class RetrievalOptimizationTests(SimpleTestCase):
    def setUp(self):
        self.settings=PersonalitySettings(base_url='https://api.deepseek.com/v1',api_key_ciphertext='fixture-cipher')
        self.role=Character(name='人物甲',source_id=12,work_name='测试作品',work_id=99,source_url='https://bgm.tv/character/12')
        self.a='人物甲在测试作品里思考替代方案，先比较路线，又决定调整行动办法。'+'遇到山路不通，他重新画出地图，依次联系伙伴，试验新的解决路径。'*5
        self.b='人物甲在测试作品里遇见困境。'+'在另一场争执里，他拒绝朋友提出的替代计划，反复沿用旧方案，失败后仍不愿尝试改变。'*5

    @patch('apps.personality.evidence._request')
    def test_distinct_pages_from_same_site_survive_while_mobile_mirrors_do_not(self,request):
        request.return_value={'results':[
            {'url':'https://baike.baidu.com/item/人物甲/123','authority':3,'title':'人物甲 测试作品','content':self.a},
            {'url':'https://wapbaike.baidu.com/item/人物甲/123?fromModule=x','authority':3,'title':'人物甲 测试作品','content':self.a},
            {'url':'https://baike.baidu.com/item/事件乙/456','authority':3,'title':'人物甲 测试作品','content':self.b},
        ]}
        result=supplement(self.role,self.settings,['divergence'])
        self.assertEqual(len(result['sources']),2)
        self.assertEqual(result['fetched'],0)
        self.assertGreater(result['filters'].get('duplicate_url',0),0)

    def test_larger_page_with_new_facts_is_not_rejected_as_a_short_biography_copy(self):
        self.assertFalse(duplicate_text(self.a+self.b,[{'text':self.a}]))
        self.assertTrue(duplicate_text(self.a,[{'text':self.a}]))

    @patch('apps.personality.evidence._request')
    def test_trusted_aliases_allow_english_body_but_wrong_work_is_rejected(self,request):
        self.role.name='露西';self.role.work_name='赛博朋克：边缘行者'
        self.role.source_stats={'identity':{'character_aliases':['Lucy','ルーシー'],'work_aliases':['Cyberpunk: Edgerunners']}}
        text='Lucy lives in Cyberpunk: Edgerunners. She adapts her strategy and considers alternative plans. '*5
        request.return_value={'results':[{'url':'https://en.wikipedia.org/wiki/Lucy','authority':3,'title':'Lucy','content':text}]}
        self.assertTrue(supplement(self.role,self.settings,['divergence'])['sources'])
        self.assertFalse(identity_matches(self.role,text.replace('Cyberpunk: Edgerunners','Another Series'),'Lucy'))
        self.assertFalse(contains_alias('A foreign student',['Rei']))
        self.assertFalse(contains_alias('Lucyfer is here',['Lucy']))

    @patch('apps.personality.evidence._request')
    def test_empty_cache_does_not_hide_a_newly_added_alias(self,request):
        self.role.name='露西';self.role.work_name='赛博朋克：边缘行者'
        text='Lucy is from Cyberpunk: Edgerunners. She chooses an alternative approach to the problem. '*5
        request.return_value={'results':[{'url':'https://en.wikipedia.org/wiki/Lucy','authority':3,'title':'Lucy','content':text}]}
        first=supplement(self.role,self.settings,['divergence']);self.assertFalse(first['sources'])
        self.assertGreater(first['filters'].get('identity_mismatch',0),0)
        self.role.evidence_cache=first['cache'];before=request.call_count
        self.role.source_stats={'identity':{'character_aliases':['Lucy'],'work_aliases':['Cyberpunk: Edgerunners']}}
        second=supplement(self.role,self.settings,['divergence'])
        self.assertTrue(second['sources']);self.assertGreater(request.call_count,before)

    def test_metadata_refresh_is_bounded_and_preserves_other_stats(self):
        self.role.pk=44;self.role.source_stats={'collects':123}
        calls=[]
        def fetch(path):
            calls.append(path)
            return {'id':12,'name':'ルーシー','infobox':[{'key':'别名','value':[{'k':'英文','v':'Lucy'}]}]} if path=='characters/12' else {'id':99,'name':'サイバーパンク エッジランナーズ','infobox':[{'key':'别名','value':[{'v':'Cyberpunk: Edgerunners'}]}]}
        hydrate_identity(self.role,fetch=fetch);hydrate_identity(self.role,fetch=fetch)
        self.assertEqual(calls,['characters/12','subjects/99'])
        self.assertEqual(self.role.source_stats['collects'],123)
        self.assertIn('Lucy',self.role.source_stats['identity']['character_aliases'])
        self.assertIn('Cyberpunk: Edgerunners',self.role.source_stats['identity']['work_aliases'])

    def test_discovery_metadata_retains_all_available_names(self):
        identity=metadata_identity({'name':'ルーシー','infobox':[{'key':'简体中文名','value':'露西'},{'key':'别名','value':[{'v':'Lucy'}]}]}, {'name':'Cyberpunk: Edgerunners','name_cn':'赛博朋克：边缘行者'})
        self.assertIn('Lucy',identity['character_aliases']);self.assertIn('露西',identity['character_aliases'])
        self.assertIn('Cyberpunk: Edgerunners',identity['work_aliases'])

    @patch('apps.personality.evidence._request')
    def test_full_body_is_matched_before_a_late_character_section_is_selected(self,request):
        body='这是页面导航和不相关的其他资料。'*1200+self.a
        request.return_value={'results':[{'url':'https://zh.wikipedia.org/wiki/long','authority':3,'title':'测试作品','content':body}]}
        result=supplement(self.role,self.settings,['divergence'])
        self.assertTrue(result['sources']);self.assertLessEqual(len(result['sources'][0]['text']),10000)
        self.assertIn('人物甲',result['sources'][0]['text'])
        self.assertIn(result['sources'][0]['text'],body)

    def test_query_plan_searches_positive_and_explicit_negative_behavior(self):
        plans=query_plan(self.role,['divergence'])
        self.assertEqual(len(plans),2)
        self.assertTrue(any('换办法' in query for query in plans));self.assertTrue(any('拒绝其他方案' in query for query in plans))
        self.assertTrue(all(len(query)<=128 and '-site:' not in query for query in plans))
        self.assertEqual(len(query_plan(self.role,['divergence'],round_number=1)),2)

    def test_late_full_width_alias_split_over_lines_keeps_original_offsets(self):
        self.role.name='露西';self.role.work_name='赛博朋克：边缘行者'
        self.role.source_stats={'identity':{'character_aliases':['Lucyna Kushinada'],'work_aliases':['Cyberpunk: Edgerunners']}}
        raw='无关的页面导航。'*2500+'Ｌｕｃｙｎａ\nＫｕｓｈｉｎａｄａ from Cyberpunk: Edgerunners tries an alternative plan.'*3
        excerpt=focus_document(raw,self.role,['divergence'])
        self.assertIn('Ｌｕｃｙｎａ',excerpt);self.assertIn(excerpt,raw);self.assertLessEqual(len(excerpt),10000)


class ReferenceOptimizationTests(TestCase):
    setUpTestData=classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp=fixtures.PersonalityTests.setUp
    character=fixtures.PersonalityTests.character

    def test_selected_id_restores_literal_text_and_keeps_scores(self):
        role=self.character();item=next(iter(evidence_registry(role).values()))
        profile=copy.deepcopy(role.profile)
        profile['dimensions']['empathy'].update(evidence_id=item['id'],quote='模型误写了这句文本')
        resolved=resolve_profile_references(profile,role);clean=validate_profile(resolved,role)
        self.assertEqual(clean['dimensions']['empathy']['quote'],item['quote'])
        self.assertEqual(clean['dimensions']['empathy']['level'],5)
        self.assertEqual(clean['dimensions']['empathy']['evidence_id'],item['id'])
        self.assertEqual(profile_fingerprint(role,clean),profile_fingerprint(role,validate_profile(clean,role)))

    def test_foreign_or_unknown_id_cannot_create_evidence(self):
        role=self.character();profile=copy.deepcopy(role.profile)
        profile['dimensions']['empathy']['evidence_id']='ev_not_in_this_character'
        with self.assertRaises(ValueError):resolve_profile_references(profile,role)

    def test_reference_ids_remain_stable_when_a_source_is_appended(self):
        role=self.character();before=set(evidence_registry(role))
        role.extra_sources=[{'url':'https://example.com/plot','text':'另一个真实来源中的一段独立剧情事实，描述人物如何重新思考。'}]
        self.assertTrue(before<=set(evidence_registry(role)))

    def test_reviewer_selects_evidence_id_without_retyping_a_quote(self):
        from .test_workflow import review_fixture
        role=self.character();item=next(iter(evidence_registry(role).values()));result=review_fixture(role)
        for row in result['dimensions']:row.update(source_evidence_id=item['id'],source_quote='模型无需抄写原文')
        check=review_profile(role,role.profile,PersonalitySettings(),lambda *args:result)
        self.assertEqual(check['status'],'passed')
        self.assertTrue(all(row['source_quote']==item['quote'] for row in check['dimensions']))

    @patch('apps.personality.catalog.complete_json')
    def test_generation_resolves_evidence_id_output(self,complete):
        role=self.character();item=next(iter(evidence_registry(role).values()));proposal=copy.deepcopy(role.profile)
        for row in proposal['dimensions'].values():row.pop('quote');row['evidence_id']=item['id']
        complete.return_value=proposal
        profile=profile_draft(role,PersonalitySettings())
        self.assertTrue(validate_profile(profile,role))
        self.assertIn('id',complete.call_args.args[2]['evidence_table']['dimensions']['empathy']['candidates'][0])

    def test_expired_admin_cannot_publish_an_approved_draft(self):
        role=self.character(status='draft')
        response=Client().post('/api/admin/personality/characters/batch-action',data='{"action":"approve","ids":['+str(role.pk)+']}',content_type='application/json')
        self.assertEqual(response.status_code,401);role.refresh_from_db();self.assertEqual(role.status,'draft')
