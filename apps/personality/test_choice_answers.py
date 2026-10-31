"""Selection-only journeys and truthful provenance; no external model calls."""
import copy
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from . import choice_answers as choices, situated_bank, questions, tests as fixtures
from .analysis import source_answers
from .followups import source_payload, validate_question
from .heartline import validate_heartline, verify_originals
from .models import Assessment, PersonalityJob
from .services import process_job, validate_answers, build_report


class ChoiceStructureTests(SimpleTestCase):
    def test_all_fixed_scenarios_have_context_specific_options_and_two_escape_routes(self):
        rows = list(zip(situated_bank.EARLY.values(), choices.EARLY.values()))
        for topic, groups in situated_bank.INTERVIEWS.items():
            rows.extend((words, choices.INTERVIEWS[topic][band]) for band, words in groups.items())
        self.assertEqual(sum(len(words) for words, _ in rows), 57)
        for words, labels in rows:
            self.assertEqual(len(words), len(labels))
            for label in labels:
                items = choices.options(label.split('|'))
                self.assertEqual(len(items), 6)
                self.assertEqual(len({item['text'] for item in items}), 6)
                self.assertEqual([item['id'] for item in items[-2:]], ['unsure', 'other'])
                for item in items:
                    self.assertLessEqual(len(item['text']), 50)
                    self.assertNotRegex(item['text'], r'MBTI|人格类型|动漫|番剧|角色|本命|[<>]')

    def test_no_blank_is_needed_and_choice_cannot_create_a_score(self):
        q = choices.early({'id':'early-energy','kind':'open','text':situated_bank.EARLY['energy'][0]}, 'energy', 0)
        step = {'questions':[q]}
        for choice in ['option-1', 'unsure']:
            result = validate_answers(step, {q['id']:{'choice':choice,'value':7,'note':''}}, complete=True)
            self.assertEqual(result[q['id']]['choice'], choice)
            self.assertIsNone(result[q['id']]['value'])
            self.assertEqual(result[q['id']]['note'], '')
        for answer in [{'choice':'made-up'}, {'choice':['option-1']}, {}, {'choice':'other','note':''}]:
            with self.assertRaises(ValueError):
                validate_answers(step, {q['id']:answer}, complete=True)
        draft = validate_answers(step, {q['id']:{'choice':'other','note':''}})
        self.assertEqual(draft[q['id']]['choice'], 'other')
        own = validate_answers(step, {q['id']:{'choice':'other','note':'独处'}}, complete=True)
        self.assertEqual(own[q['id']]['note'], '独处')
        old_client = validate_answers(step, {q['id']:{'note':'自己的简短回答也可以保存。'}}, complete=True)
        self.assertEqual(old_client[q['id']]['choice'], 'other')

    def test_new_policy_is_snapshotted_and_old_interviews_remain_unchanged(self):
        steps = questions.initial_steps('selection')
        self.assertTrue(choices.active(steps))
        self.assertTrue(all(q.get('options') for step in steps for q in step['questions'] if q['kind']=='open'))
        old = copy.deepcopy(steps)
        old[0].pop('response_policy')
        for step in old:
            for q in step['questions']:
                q.pop('options', None);q.pop('response_policy', None)
        original = copy.deepcopy(old)
        self.assertTrue(all('options' not in q for q in questions.interview_step(old, {}, 'history')['questions']))
        self.assertEqual(old, original)
        for seed in range(50):
            self.assertTrue(all(q.get('options') for q in questions.interview_step(steps, {}, seed)['questions']))

    def test_fallback_probes_are_also_selectable(self):
        steps = questions.initial_steps('fallback')
        q = next(q for s in steps for q in s['questions'] if q['kind']=='open')
        answer = {'note':'我需要看当天自己的精力，不过通常会想先安静一会儿。'}
        result = questions.followup_step(steps, {q['id']:answer})
        self.assertTrue(result['questions'])
        self.assertTrue(all(item.get('options') for item in result['questions']))
        self.assertEqual(result['questions'][0]['source_quote'], answer['note'])


class ChoiceJourneyTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    create = fixtures.PersonalityTests.create
    character = fixtures.PersonalityTests.character

    @staticmethod
    def followup_result(payload):
        anchor = payload['anchor']
        return {'done':False, 'source_question_id':anchor['question_id'], 'source_quote':'',
                'source_choice_id':anchor['selection']['id'], 'focus':anchor['focus'],
                'question':'回看刚才选择的那个做法，什么最影响你作出这个决定？' if payload['batch']=='round_1' else '在刚才的情况下，哪一件小事最可能让你改变原来的决定？',
                'options':['自己当时的时间和精力', '之前已经答应或安排好的事情', '这件事对自己或者别人的重要程度']}

    def core(self, unsure=False):
        fixtures.ready_ai_fixture()
        state = self.create(ai_consent=True)
        while state['status']=='active':
            if state['step'].get('ai_followup', {}).get('state')=='pending':
                job=PersonalityJob.objects.get(assessment_id=state['id'], kind='followup',status='queued')
                with patch('apps.personality.services.complete_json', side_effect=lambda settings,prompt,payload:self.followup_result(payload)):
                    process_job(job.pk)
                state=self.client.get('/api/personality/assessments/'+state['id']).json()
                continue
            answers={q['id']:{'value':5 if q['kind']=='scale' else None, 'note':'', 'skipped':False,
                     **({'choice':'unsure' if unsure else 'option-1'} if q.get('options') else {})}
                     for q in state['step']['questions']}
            self.assertTrue(all(q['kind']=='scale' or q.get('options') for q in state['step']['questions']))
            response=self.send('/api/personality/assessments/'+state['id'],{'revision':state['revision'],'answers':answers,'complete':True})
            self.assertEqual(response.status_code,200,response.content)
            state=response.json()
        return Assessment.objects.get(pk=state['id'])

    def test_entire_journey_and_ai_character_report_without_any_typed_text(self):
        from .test_analysis import persona_fixture, match_fixture
        row=self.core();self.assertEqual(row.status,'ready')
        self.assertTrue(all(not answer['note'] for answer in row.answers.values()))
        self.assertEqual(PersonalityJob.objects.filter(assessment=row,kind='followup').count(),2)
        self.assertTrue(all(s['ai_followup']['state']=='generated' for s in row.steps if 'ai_followup' in s))
        original=copy.deepcopy(row.answers);scores=questions.quantified(row.steps,row.answers)
        source,_=source_answers(row)
        self.assertEqual(source['open-conflict']['selection']['id'],'option-1')
        self.assertEqual(source['open-conflict']['note'],'')
        role=self.character();persona=persona_fixture(row,build_report(row))
        persona['quote']={}
        persona['heartline']={'question_id':'open-conflict','choice_id':'option-1','text':'我想先照顾好自己的安排，再决定能帮忙多少。'}
        with patch('apps.personality.services.complete_json',side_effect=[persona,match_fixture(role)]):
            response=self.send('/api/personality/assessments/'+str(row.pk)+'/submit')
            self.assertEqual(response.status_code,202)
            process_job(PersonalityJob.objects.get(assessment=row,kind='report').pk)
        row.refresh_from_db()
        self.assertEqual(row.status,'completed')
        self.assertEqual(row.report['character']['id'],role.pk)
        self.assertEqual(len(row.report['sections']),10)
        self.assertEqual(row.report['heartline']['origin'],'ai_from_choices')
        self.assertEqual(row.report['quote']['text'],'')
        self.assertEqual(row.answers,original)
        self.assertEqual(questions.quantified(row.steps,row.answers),scores)

    def test_unsure_answers_finish_but_are_not_treated_as_positive_evidence(self):
        row=self.core(unsure=True)
        source,_=source_answers(row)
        self.assertEqual(row.status,'ready')
        self.assertNotIn('open-conflict',source)
        self.assertNotIn('early-energy',source)
        self.assertEqual(row.answers['open-conflict']['choice'],'unsure')

    def test_selection_is_taken_from_snapshot_and_optional_note_is_kept_separate(self):
        state=self.create(ai_consent=True);row=Assessment.objects.get(pk=state['id'])
        q=next(q for q in row.steps[0]['questions'] if q.get('options'))
        row.answers={q['id']:{'choice':'option-1','note':'但是这取决于我当天的精力。','value':None,'skipped':False,'selection':{'id':'fake','text':'伪造的客户端文案'}}}
        source,_=source_answers(row)
        self.assertEqual(source[q['id']]['selection'],q['options'][0])
        self.assertEqual(source[q['id']]['note'],row.answers[q['id']]['note'])
        row.steps.append({'questions':[],'ai_followup':{'round':1,'state':'pending'}});row.step_index=len(row.steps)-1
        payload=source_payload(row)
        result=self.followup_result(payload)
        item=validate_question(result,payload,row)
        self.assertEqual(item['source_selection'],q['options'][0]['text'])
        self.assertNotIn('source_quote',item)
        for changes in [{'options':['重复的一个选项']*3}, {'options':['一个正常的选项','另一个正常选项','你喜欢什么动漫角色']}, {'source_choice_id':'option-99'}, {'options':None}]:
            with self.assertRaises(ValueError):validate_question({**result,**changes},payload,row)

    def test_heartline_from_selection_is_not_a_literal_quote_and_needs_exact_source(self):
        source={'q':{'kind':'open','question':'具体情境','note':'','selection':{'id':'option-1','text':'先保留一点独处的时间'}}}
        line={'question_id':'q','choice_id':'option-1','text':'我想给自己留一点安静的时间。'}
        clean=validate_heartline(line,source)
        self.assertEqual(clean['origin'],'ai_from_choices')
        report={'heartline':clean,'quote':{'question_id':'q','text':source['q']['selection']['text']}}
        verify_originals(report,{'q':{'choice':'option-1','note':''}})
        self.assertEqual(report['quote']['text'],'')
        self.assertEqual(report['heartline'],clean)
        verify_originals(report,{'q':{'choice':'option-2','note':''}})
        self.assertEqual(report['heartline'],{})
        self.assertEqual(validate_heartline({**line,'choice_id':'option-2'},source),{})
