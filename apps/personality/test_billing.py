from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.points.models import PointAccount, PointLedger
from apps.points.services import save_rules
from .models import Assessment, timestamp
from .tests import ready_ai_fixture


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AssessmentBillingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='billing-user', password='test-password', created_at=timestamp())
        PointAccount.objects.create(user=self.user, balance=20, updated_at=timestamp())
        self.client.force_login(self.user)
        ready_ai_fixture()

    def start(self, key='request-0001', **changes):
        body = dict(ai_consent=True, points_consent=True, expected_cost=10, client_key=key)
        body.update(changes)
        return self.client.post('/api/personality/assessments', body, content_type='application/json')

    def balance(self):
        return PointAccount.objects.get(user=self.user).balance

    def test_start_and_retry_charge_once_then_reject_insufficient(self):
        first = self.start()
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(first.json()['payment'], dict(points=10, balance=10, replayed=False))
        retry = self.start()
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.json()['id'], retry.json()['id'])
        self.assertTrue(retry.json()['payment']['replayed'])
        self.assertEqual(self.balance(), 10)
        self.assertEqual(self.start('request-0002').status_code, 201)
        self.assertEqual(self.start('request-0003').status_code, 402)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(Assessment.objects.count(), 2)
        self.assertEqual(PointLedger.objects.filter(event_type='personality_start').count(), 2)

    def test_requires_explicit_current_price_consent_and_key(self):
        for changes in [dict(points_consent=False), dict(expected_cost=0), dict(expected_cost=True), dict(client_key=''), dict(ai_consent=False)]:
            self.assertEqual(self.start(**changes).status_code, 400)
        self.assertFalse(Assessment.objects.exists())
        self.assertEqual(self.balance(), 20)

    def test_service_unavailable_or_frozen_never_charges(self):
        with patch('apps.personality.billing.ai_service_status', return_value=(False, '暂未就绪')):
            self.assertEqual(self.start().status_code, 503)
        PointAccount.objects.filter(user=self.user).update(status='frozen')
        self.assertEqual(self.start().status_code, 403)
        self.assertFalse(PointLedger.objects.exists())
        self.assertFalse(Assessment.objects.exists())

    def test_creation_failure_rolls_back_assessment_and_points(self):
        with patch('apps.personality.billing.apply_ledger', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):
                self.start()
        self.assertEqual(self.balance(), 20)
        self.assertFalse(Assessment.objects.exists())

    def test_resume_read_and_deleted_request_do_not_charge_again(self):
        response = self.start()
        url = '/api/personality/assessments/' + response.json()['id']
        self.assertEqual(self.client.get(url).status_code, 200)
        state = self.client.get(url).json()
        updated = self.client.post(url, dict(revision=state['revision'], action='authorize_ai', ai_consent=True), content_type='application/json')
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(self.balance(), 10)
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.start().status_code, 410)
        self.assertEqual(self.balance(), 10)

    def test_setting_price_and_free_mode_are_used_by_server(self):
        save_rules(dict(personality_assessment_cost=15), 'fixture')
        self.assertEqual(self.start().status_code, 400)
        self.assertEqual(self.start(expected_cost=15).status_code, 201)
        self.assertEqual(self.balance(), 5)
        config = self.client.get('/api/personality/config')
        self.assertEqual(config.json()['cost'], 15)
        self.assertEqual(config.json()['balance'], 5)
        self.assertIn('no-store', config['Cache-Control'])
        save_rules(dict(personality_assessment_cost=0), 'fixture')
        self.assertEqual(self.start('free-request', expected_cost=0).status_code, 201)
        self.assertEqual(self.balance(), 5)

