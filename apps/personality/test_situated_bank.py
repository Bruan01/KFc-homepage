"""Bank integrity and scoring/version regressions, not psychometric validation."""
import copy

from django.test import SimpleTestCase, TestCase

from . import plain_bank, questions, scenario_bank, situated_bank as bank
from .clarifications import followup_step
from .question_bank import BASE_EXTRA, EXTENDED_EXTRA


def historic_steps(source, version):
    items = []
    for prefix, original, extra, count in [('base', questions.BASE, BASE_EXTRA, 6), ('dim', questions.EXTENDED, EXTENDED_EXTRA, 4)]:
        wording = source.BASE if prefix == 'base' else source.EXTENDED
        for key in original:
            for i, (_, reverse) in enumerate((original[key]+extra[key])[:count]):
                items.append({**questions.scale_item(prefix, key, i, (wording[key][i], reverse)), 'wording_version': version})
    steps = [{'title': '历史题面', 'questions': items[i:i+8]} for i in range(0, len(items), 8)]
    for position, topic, focus in [(0, 'energy', 'IE'), (3, 'values', 'FT')]:
        steps[position]['questions'].append({'id': 'early-'+topic, 'kind':'open', 'focus':focus,
            'text':source.EARLY[topic][0], 'wording_version':version})
    return steps


class SituatedBankTests(SimpleTestCase):
    def test_candidate_pool_expands_without_exact_duplicates_or_blind_test_leaks(self):
        numeric = [q for groups in [bank.BASE, bank.EXTENDED, bank.DISTINGUISH] for items in groups.values() for q in items]
        opened = [q for items in bank.EARLY.values() for q in items]+[q for groups in bank.INTERVIEWS.values() for items in groups.values() for q in items]
        self.assertEqual(len(numeric), 152)
        self.assertEqual(len(opened), 57)
        words = [q['text'] for q in numeric]+opened
        self.assertEqual(len(words), 209)
        self.assertEqual(len(set(words)), len(words))
        for question in numeric:
            self.assertIs(type(question['reverse']), bool)
            self.assertIn(question['facet'], bank.FACETS)
            self.assertLessEqual(len(question['text']), 68)
        for text in words:
            self.assertNotRegex(text, r'MBTI|动漫|番剧|角色|本命|二次元|认知功能|情境限制|人格等级')
            self.assertLessEqual(text.count('？')+text.count('?'), 1)
        for text in opened:
            self.assertEqual(text.count('？'), 1)
        for topic, words in bank.EARLY.items():
            self.assertEqual(len(words), len(bank.EARLY_FACETS[topic]))
            self.assertTrue(all(facet in bank.FACETS for facet in bank.EARLY_FACETS[topic]))
        for topic, groups in bank.INTERVIEWS.items():
            for branch, words in groups.items():
                self.assertEqual(len(words), len(bank.INTERVIEW_FACETS[topic][branch]))
                self.assertTrue(all(facet in bank.FACETS for facet in bank.INTERVIEW_FACETS[topic][branch]))

    def test_many_seeds_keep_direction_balance_facet_coverage_and_test_length(self):
        for seed in range(120):
            steps = questions.initial_steps(seed=seed)
            all_items = [q for step in steps for q in step['questions']]
            self.assertEqual(len(all_items), 50)
            self.assertEqual(len({q['id'] for q in all_items}), 50)
            self.assertEqual(steps, questions.initial_steps(seed=seed))
            for key in [*questions.AXES, *questions.DIMENSIONS]:
                selected = [q for q in all_items if q.get('target') == key]
                self.assertEqual(len(selected), 6 if key in questions.AXES else 4)
                self.assertEqual(sum(q['reverse'] for q in selected), 3) if key in questions.AXES else self.assertIn(sum(q['reverse'] for q in selected), [1, 2])
                pool = bank.BASE.get(key, bank.EXTENDED.get(key))
                self.assertEqual({q['facet'] for q in selected}, {q['facet'] for q in pool})
            verify = questions.discrimination_step(steps, {})
            self.assertEqual(len(verify['questions']), 6)
            self.assertEqual(verify, questions.discrimination_step(steps, {}))
            for key in {q['target'] for q in verify['questions']}:
                self.assertEqual({q['reverse'] for q in verify['questions'] if q['target'] == key}, {False, True})
            self.assertEqual(len(questions.interview_step(steps, {}, seed=seed)['questions']), 3)

    def test_explicit_keying_matches_every_shown_statement_and_round_trips_both_extremes(self):
        steps = questions.initial_steps('keying')
        steps.append(questions.discrimination_step(steps, {}))
        for step in steps:
            for q in step['questions']:
                if q['kind'] != 'scale':continue
                prefix, key, i = q['id'].split('-');i=int(i)
                source = {'base':bank.BASE, 'dim':bank.EXTENDED, 'verify':bank.DISTINGUISH}[prefix][key][i]
                self.assertEqual((q['text'], q['reverse'], q['facet']), (source['text'], source['reverse'], source['facet']))
        high = {q['id']:{'value':1 if q['reverse'] else 7} for s in steps for q in s['questions'] if q['kind']=='scale'}
        low = {key:{'value':8-answer['value']} for key, answer in high.items()}
        self.assertTrue(all(score['value']==100 for score in questions.quantified(steps, high).values()))
        self.assertTrue(all(score['value']==0 for score in questions.quantified(steps, low).values()))
        for qid in list(high):
            if qid.startswith('dim-recovery-'):high[qid]={'value':None,'skipped':True}
        self.assertIsNone(questions.quantified(steps,high)['recovery']['value'])

    def test_previous_pool_items_are_avoided_when_unused_candidates_exist(self):
        first = questions.initial_steps('first')
        used = {q['id'] for s in first for q in s['questions'] if q['kind']=='scale'}
        second = questions.initial_steps('second', previous_ids=used)
        picked = {q['id'] for s in second for q in s['questions'] if q['kind']=='scale'}
        self.assertFalse(used & picked)

    def test_historic_future_rounds_still_use_v3_and_v4_banks_and_original_scoring(self):
        for source, version in [(scenario_bank, 'xinying-3'), (plain_bank, 'xinying-4')]:
            steps = historic_steps(source, version);before = copy.deepcopy(steps)
            answers = {q['id']:{'value':1 if q['reverse'] else 7} for s in steps for q in s['questions'] if q['kind']=='scale'}
            verify = questions.discrimination_step(steps, answers)
            for q in verify['questions']:
                _,key,index=q['id'].split('-')
                self.assertEqual(q['text'],source.DISTINGUISH[key][int(index)])
            for q in questions.interview_step(steps, answers, seed='history')['questions']:
                topic=q['id'].removeprefix('open-')
                self.assertIn(q['text'],source.INTERVIEWS[topic]['high'])
                self.assertEqual(q['wording_version'],version)
            self.assertEqual(steps,before)
            self.assertTrue(all(s['value']==100 for s in questions.quantified(steps,answers).values()))

    def test_new_comparisons_use_explicit_facets_not_historic_id_assumptions(self):
        q1 = {**questions.scale_item('base','IE',0,(bank.BASE['IE'][0]['text'],False)), 'wording_version':bank.VERSION,'facet':'recharge'}
        q2 = {**questions.scale_item('base','IE',1,(bank.BASE['IE'][1]['text'],False)), 'wording_version':bank.VERSION,'facet':'companionship'}
        answers={q1['id']:{'value':7},q2['id']:{'value':1}}
        self.assertIsNone(followup_step([{'questions':[q1,q2]}],answers))
        q2 = {**questions.scale_item('base','IE',5,(bank.BASE['IE'][5]['text'],False)), 'wording_version':bank.VERSION,'facet':'recharge'}
        answers = {q1['id']:{'value':7},q2['id']:{'value':1}}
        compared=followup_step([{'questions':[q1,q2]}],answers)
        self.assertEqual(compared['questions'][0]['evidence'],[q1['id'],q2['id']])


class StoredBankCompatibilityTests(TestCase):
    def test_starting_note_keeps_its_specific_facet_in_prompt_and_fallback(self):
        from types import SimpleNamespace
        from .followups import source_payload
        question = {'id':'open-action','kind':'open','focus':'execution','facet':'starting','wording_version':bank.VERSION,
                    'text': bank.INTERVIEWS['action']['low'][0]}
        row = SimpleNamespace(steps=[{'questions':[question]}, {'questions':[], 'ai_followup':{'round':1,'state':'pending'}}],
            step_index=1, answers={'open-action':{'value':None,'note':'东西已经准备好，我还是想再看看资料，担心第一步选错。','skipped':False}})
        payload = source_payload(row)
        self.assertEqual(payload['anchor']['facet'], 'starting')
        result = followup_step(row.steps, row.answers)['questions'][0]
        self.assertIn('开始动手', result['text'])
        self.assertNotIn('对方', result['text'])

    def test_advancing_an_existing_v4_record_does_not_swap_its_next_rounds(self):
        from apps.accounts.models import User
        from .models import Assessment, timestamp
        from .services import advance
        user=User.objects.create_user(username='v4-snapshot-owner',password='fixture',created_at=timestamp())
        steps=historic_steps(plain_bank,'xinying-4')
        answers={q['id']:{'value':5 if q['kind']=='scale' else None,'note':'原始回答保留，不为新版题面重写。' if q['kind']=='open' else '', 'skipped':False} for s in steps for q in s['questions']}
        row=Assessment.objects.create(user=user,version='xinying-4',steps=steps,answers=answers,step_index=5)
        original=copy.deepcopy(row.answers);initial=copy.deepcopy(row.steps)
        advance(row);row.save();row.refresh_from_db()
        self.assertEqual(row.steps[:6],initial)
        self.assertEqual(row.answers,original)
        for q in row.steps[6]['questions']:
            _,key,index=q['id'].split('-')
            self.assertEqual(q['text'],plain_bank.DISTINGUISH[key][int(index)])
        for q in row.steps[7]['questions']:
            self.assertIn(q['text'],plain_bank.INTERVIEWS[q['id'].removeprefix('open-')][q['branch']])
