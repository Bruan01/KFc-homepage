import json
from unittest.mock import patch

from django.test import Client, TestCase

from .models import PersonalitySettings


class ModelSettingsTests(TestCase):
    def setUp(self):
        self.admin = Client()
        session = self.admin.session
        session['admin_username'] = 'root'
        session['admin_level'] = 3
        session['admin_is_super'] = True
        session.save()
        self.settings = PersonalitySettings.objects.create(
            base_url='https://example.com/v1', model='test-model', updated_by='root', ai_enabled=True)

    def post(self, path, body=None):
        return self.admin.post('/api/admin/personality/'+path, json.dumps(body or {}), content_type='application/json')

    def public(self):
        return self.admin.get('/api/admin/personality/settings').json()['settings']

    @patch('apps.personality.views.complete_json', return_value={'ok': True})
    def test_saved_connection_check_survives_reload_without_secrets(self, complete):
        self.assertEqual(self.public()['connection_check']['status'], 'unchecked')
        self.assertEqual(self.post('test').status_code, 200)
        data = self.public()
        self.assertEqual(data['connection_check']['status'], 'passed')
        self.assertTrue(data['connection_check']['checked_at'])
        self.assertTrue(data['saved'])
        self.assertNotIn('fingerprint', json.dumps(data))
        self.assertNotIn('api_key_ciphertext', data)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.provider_check['status'], 'passed')

    @patch('apps.personality.views.complete_json', side_effect=ValueError('文本服务鉴权失败'))
    def test_failure_is_saved_and_does_not_remove_connection(self, complete):
        self.assertEqual(self.post('test').status_code, 400)
        data = self.public()
        self.assertEqual(data['connection_check']['status'], 'failed')
        self.assertIn('鉴权失败', data['connection_check']['error'])
        self.assertEqual(data['model'], 'test-model')

    @patch('apps.personality.views.complete_json', return_value={'ok': True})
    def test_connection_edit_invalidates_check_but_quota_edit_preserves_it(self, complete):
        self.post('test')
        self.assertEqual(self.post('settings', {'daily_reports_per_user': 7}).status_code, 200)
        self.assertEqual(self.public()['connection_check']['status'], 'passed')
        self.assertEqual(self.post('settings', {'model': 'changed-model'}).status_code, 200)
        self.assertEqual(self.public()['connection_check']['status'], 'unchecked')
        self.assertEqual(self.public()['connection_check']['checked_at'], '')

    @patch('apps.personality.views.complete_json', return_value={'ok': True})
    def test_unsaved_and_stale_tests_do_not_certify_saved_connection(self, complete):
        self.post('test', {'model': 'unsaved-model'})
        self.assertEqual(self.public()['connection_check']['status'], 'unchecked')
        def changed_during_test(*args):
            PersonalitySettings.objects.filter(pk=1).update(model='new-model')
            return {'ok': True}
        complete.side_effect = changed_during_test
        self.post('test')
        self.assertEqual(self.public()['connection_check']['status'], 'unchecked')

    @patch('apps.personality.views.complete_json', return_value={'ok': True})
    def test_check_does_not_enable_a_disabled_service(self, complete):
        PersonalitySettings.objects.filter(pk=1).update(ai_enabled=False)
        self.post('test')
        self.assertFalse(self.public()['ai_enabled'])

    def test_settings_page_keeps_advanced_fields_and_removes_copy_actions(self):
        response = self.admin.get('/admin/personality/settings')
        text = b''.join(response.streaming_content).decode() if response.streaming else response.content.decode()
        self.assertNotIn('data-copy', text)
        self.assertNotIn('开放新测评', text)
        self.assertIn('已保存的服务', text)
        self.assertIn('<details class="model-advanced">', text)
        self.assertIn('name="enabled"', text)
