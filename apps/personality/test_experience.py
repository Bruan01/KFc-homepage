from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from . import tests as fixtures
from .catalog import validate_profile
from .heartline import ensure_heartline, verify_originals
from .questions import quantified
from .services import process_job
from .test_single_report import SingleReportJourneyTests


class FiveScaleCompatibilityTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send

    def test_new_assessment_uses_five_choices_and_rejects_six(self):
        fixtures.ready_ai_fixture()
        response = self.send('/api/personality/assessments', {'ai_consent': True})
        self.assertEqual(response.status_code, 201)
        state = response.json()
        self.assertEqual(state['step']['response_scale'], 5)
        question = next(q for q in state['step']['questions'] if q['kind'] == 'scale')
        endpoint = '/api/personality/assessments/' + state['id']
        invalid = self.send(endpoint, {'revision': state['revision'], 'answers': {question['id']: {'value': 6, 'note': '', 'skipped': False}}})
        self.assertEqual(invalid.status_code, 400)
        valid = self.send(endpoint, {'revision': state['revision'], 'answers': {question['id']: {'value': 5, 'note': '', 'skipped': False}}})
        self.assertEqual(valid.status_code, 200)

    def test_five_and_legacy_seven_scales_keep_their_own_formula(self):
        questions = [{'id': f'q{index}', 'kind': 'scale', 'target': 'IE', 'reverse': reverse} for index, reverse in enumerate([False, False, True, True])]
        answers = {f'q{index}': {'value': value} for index, value in enumerate([1, 5, 1, 5])}
        five = quantified([{'response_scale': 5, 'questions': questions}], answers)['IE']['value']
        self.assertEqual(five, 50)
        legacy_answers = {f'q{index}': {'value': value} for index, value in enumerate([1, 7, 1, 7])}
        legacy = quantified([{'questions': questions}], legacy_answers)['IE']['value']
        self.assertEqual(legacy, 50)


class CharacterRecommendationTests(TestCase):
    setUpTestData = classmethod(fixtures.PersonalityTests.setUpTestData.__func__)
    setUp = fixtures.PersonalityTests.setUp
    send = fixtures.PersonalityTests.send
    character = fixtures.PersonalityTests.character
    finish = fixtures.PersonalityTests.finish
    create = fixtures.PersonalityTests.create
    public_finish = SingleReportJourneyTests.public_finish
    combined = SingleReportJourneyTests.combined
    submit = SingleReportJourneyTests.submit
    prepare = SingleReportJourneyTests.prepare

    def test_report_has_five_other_characters_one_opposite_and_reviewed_quote(self):
        row = self.prepare()
        self.role.profile['signature_quote'] = {'text': '他会察觉他人的难处', 'source_url': self.role.source_url}
        self.role.save(update_fields=['profile'])
        for index in range(6):
            self.character(name=f'其它角色{index}', work_name=f'其它作品{index}')
        with patch('apps.personality.services.complete_json', side_effect=lambda config, prompt, payload: self.combined(row, payload)):
            job = self.submit(row)
            process_job(job.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, 'completed')
        self.assertEqual(len(row.report['other_characters']), 5)
        self.assertIsNotNone(row.report['opposite_character'])
        self.assertNotEqual(row.report['opposite_character']['id'], row.report['character']['id'])
        self.assertTrue(row.report['character']['source_quote'])
        self.assertNotIn('mbti', row.report['character'])

    def test_signature_quote_must_exist_in_its_source(self):
        role = self.character()
        role.profile['signature_quote'] = {'text': '这不是角色说过的台词', 'source_url': role.source_url}
        with self.assertRaises(ValueError):
            validate_profile(role.profile, role)
        role.extra_sources = [{'url': 'https://example.org/quote', 'text': '这是一句有来源的角色台词'}]
        role.profile['signature_quote'] = {'text': '这是一句有来源的角色台词', 'source_url': 'https://example.org/quote'}
        clean = validate_profile(role.profile, role)
        self.assertEqual(clean['signature_quote']['text'], '这是一句有来源的角色台词')


class HeartlineFallbackTests(SimpleTestCase):
    def test_original_quote_is_used_when_ai_heartline_is_empty(self):
        report = {'quote': {'text': '我想先照顾自己的安排。', 'question_id': 'q'}, 'heartline': {}}
        ensure_heartline(report, {})
        self.assertEqual(report['heartline']['origin'], 'literal_quote')
        verify_originals(report, {'q': {'note': '我想先照顾自己的安排。', 'choice': None}})
        self.assertEqual(report['heartline']['text'], '我想先照顾自己的安排。')

    def test_actual_choice_is_used_when_no_quote_exists(self):
        source = {'q': {'selection': {'id': 'rest', 'text': '我想先休息'}, 'note': ''}}
        report = {'quote': {}, 'heartline': {}}
        ensure_heartline(report, source)
        verify_originals(report, {'q': {'note': '', 'choice': 'rest', 'skipped': False}})
        self.assertEqual(report['heartline']['origin'], 'choice_refined')
        self.assertEqual(report['heartline']['text'], '你不必时时照顾世界，给自己留一点安静，也是一种温柔的勇敢。')
        self.assertTrue(report['heartline']['text'].startswith('你'))

    def test_unrelated_choice_does_not_produce_a_fragment(self):
        source = {'q': {'selection': {'id': 'plain', 'text': '这是一个没有对应表达的选项'}, 'note': ''}}
        report = {'quote': {}, 'heartline': {}}
        ensure_heartline(report, source)
        self.assertNotIn('text', report['heartline'])


class ExperienceMarkupTests(SimpleTestCase):
    def read(self, relative):
        return (Path(settings.BASE_DIR) / relative).read_text(encoding='utf-8')

    def test_save_dialog_is_image_only_and_analysis_link_is_removed(self):
        html = self.read('static/personality/report.html')
        self.assertNotIn('analysis-process-link', html)
        self.assertNotIn('include-answers', html)
        self.assertNotIn('download-report', html)
        self.assertNotIn('print-report', html)
        self.assertIn('value="short" checked', html)
        self.assertIn('value="long"', html)
        exporter = self.read('static/personality/save-image.js')
        self.assertNotIn('navigator.share', exporter)
        self.assertIn('anchor.download=filename', exporter)
        self.assertIn('保存到相册', exporter)
        self.assertIn("Math.min(1,12000/height)", exporter)

    def test_progress_stage_theme_scale_and_axis_direction_are_present(self):
        app = self.read('static/personality/app.js')
        self.assertIn('response_scale||7', app)
        self.assertIn('总阶段', app)
        self.assertIn('container.dataset.stage', app)
        report = self.read('static/personality/report.js')
        self.assertIn('axis.value<50', report)
        self.assertIn('100-axis.value', report)
