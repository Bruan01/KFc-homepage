"""Regression coverage for unrelated probes and unexplained answer comparisons."""
from types import SimpleNamespace
from django.test import TestCase

from . import questions, plain_bank, scenario_bank
from .clarifications import followup_step
from .followups import source_payload, validate_question


class QuestionClarityTests(TestCase):
    def test_effort_reply_is_not_routed_to_relationships_by_word_needs(self):
        steps = [{'questions': [{'id': 'open-action', 'kind': 'open', 'focus': 'execution', 'text': '你会根据什么决定是否继续做一件事？'}]}]
        note = '我会解释这件事花了很多精力，并不是每件事情都需要投入很多时间；如果是自己感兴趣的，我也可以认真。'
        result = followup_step(steps, {'open-action': {'note': note, 'value': None, 'skipped': False}})
        item = result['questions'][0]
        self.assertEqual(item['focus'], 'execution'); self.assertEqual(item['evidence'], ['open-action'])
        self.assertEqual(item['source_quote'], note); self.assertNotIn('对方', item['text'])
        self.assertEqual(len(result['questions']), 1)

    def test_pattern_probe_names_the_actual_questions_and_original_answers(self):
        steps = [{'questions': [
            {'id': 'a', 'kind': 'scale', 'target': 'IE', 'reverse': False, 'text': '聚会后我想自己待一会儿。'},
            {'id': 'b', 'kind': 'scale', 'target': 'IE', 'reverse': False, 'text': '我通常想先自己理清想法再说。'}]}]
        answers = {'a': {'value': 7, 'note': '', 'skipped': False}, 'b': {'value': 1, 'note': '', 'skipped': False}}
        item = followup_step(steps, answers)['questions'][0]
        self.assertEqual(item['id'], 'follow-pattern'); self.assertEqual(item['evidence'], ['a', 'b'])
        self.assertEqual([r['value'] for r in item['context_items']], [7, 1])
        self.assertEqual([r['text'] for r in item['context_items']], [q['text'] for q in steps[0]['questions']])
        self.assertNotIn('内向', item['text']); self.assertNotIn('矛盾', item['text'])

    def test_skipped_comment_and_unknown_question_cannot_become_a_probe(self):
        steps = [{'questions': [{'id': 'open-action', 'kind': 'open', 'focus': 'execution', 'text': '最近什么影响了你做事？'}]}]
        answers = {'open-action': {'value': None, 'note': '以前会勉强，现在想休息。', 'skipped': True},
                   'unknown': {'value': None, 'note': '但是我不确定应该怎么办。', 'skipped': False}}
        self.assertIsNone(followup_step(steps, answers))

    def test_agreeing_with_different_facets_does_not_create_a_false_conflict(self):
        first = {'id': 'base-IE-0', 'kind': 'scale', 'target': 'IE', 'reverse': False, 'text': plain_bank.BASE['IE'][0]}
        other = {'id': 'base-IE-4', 'kind': 'scale', 'target': 'IE', 'reverse': True, 'text': plain_bank.BASE['IE'][4]}
        answers = {q['id']: {'value': 7, 'note': '', 'skipped': False} for q in [first, other]}
        self.assertIsNone(followup_step([{'questions': [first, other]}], answers))
        other = {'id': 'base-IE-1', 'kind': 'scale', 'target': 'IE', 'reverse': False, 'text': plain_bank.BASE['IE'][1]}
        answers = {first['id']: {'value': 7, 'note': '', 'skipped': False}, other['id']: {'value': 1, 'note': '', 'skipped': False}}
        self.assertIsNone(followup_step([{'questions': [first, other]}], answers))

    def test_ai_anchor_keeps_original_question_topic_and_rejects_topic_switch(self):
        note = '不是每件事都需要投入很多时间，我更愿意认真做自己感兴趣的事。'
        row = SimpleNamespace(steps=[{'questions': [{'id': 'open-action', 'kind': 'open', 'focus': 'execution', 'text': '你怎样决定为一件事投入多少时间？'}]},
                                    {'questions': [], 'ai_followup': {'round': 1, 'state': 'pending'}}], step_index=1,
                              answers={'open-action': {'note': note, 'value': None, 'skipped': False}})
        payload = source_payload(row)
        self.assertEqual(payload['anchor']['focus'], 'execution')
        result = {'done': False, 'source_question_id': 'open-action', 'source_quote': note,
                  'focus': 'boundary', 'question': '在你刚才说的情况下，你会怎样告诉对方自己的决定？'}
        with self.assertRaises(ValueError): validate_question(result, payload, row)
        result.update(focus='execution', question='对你来说，什么样的事情值得花更多时间？')
        self.assertEqual(validate_question(result, payload, row)['focus'], 'execution')

    def test_old_v3_unfinished_interview_keeps_its_bank(self):
        steps = [{'questions': [{'id': 'base-IE-0', 'kind': 'scale', 'target': 'IE', 'reverse': False,
                                'text': scenario_bank.BASE['IE'][0], 'wording_version': 'xinying-3'}]}]
        interview = questions.interview_step(steps, {}, seed='existing')
        for q in interview['questions']:
            topic = q['id'].removeprefix('open-')
            self.assertIn(q['text'], scenario_bank.INTERVIEWS[topic]['middle'])
        self.assertEqual(steps[0]['questions'][0]['text'], scenario_bank.BASE['IE'][0])

    def test_plain_bank_retains_complete_pools_and_scoring_keys(self):
        from .question_bank import BASE_EXTRA, EXTENDED_EXTRA
        for original, extra, bank in [(questions.BASE, BASE_EXTRA, plain_bank.BASE), (questions.EXTENDED, EXTENDED_EXTRA, plain_bank.EXTENDED)]:
            for key, items in original.items(): self.assertEqual(len(items+extra[key]), len(bank[key]))
        self.assertEqual(sum(len(v) for v in plain_bank.BASE.values())+sum(len(v) for v in plain_bank.EXTENDED.values())+
                         sum(len(v) for v in plain_bank.DISTINGUISH.values())+sum(len(v) for v in plain_bank.EARLY.values())+
                         sum(len(v) for topic in plain_bank.INTERVIEWS.values() for v in topic.values()), 143)
        self.assertEqual(questions.VERSION, 'xinying-4')
