from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.points.models import PointLedger
from apps.points.services import save_rules


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RegistrationRewardTests(TestCase):
    def register(self):
        with patch('apps.accounts.views.consume_verification_code', return_value=None), patch('apps.accounts.views.mailing.notify_user_registered'):
            return self.client.post('/api/user/register', dict(username='reward-new', email='reward-new@example.com', password='test-password', code='123456'), content_type='application/json')

    def test_registration_receipt_explains_real_award_and_uses(self):
        response = self.register()
        self.assertEqual(response.status_code, 200, response.content)
        reward = response.json()['registration_reward']
        self.assertEqual(reward['points'], 20)
        self.assertTrue(reward['awarded'])
        self.assertEqual(reward['personality_cost'], 10)
        self.assertEqual(reward['imaging_cost'], 10)
        self.assertTrue(reward['first_post']['eligible'])
        self.assertEqual(reward['first_post']['points'], 10)
        self.assertEqual(PointLedger.objects.get(event_type='registration_reward').delta, 20)

    def test_configured_amounts_are_not_hardcoded_in_receipt(self):
        save_rules(dict(registration_reward=35, personality_assessment_cost=15, image_generation_default_cost=8), 'fixture')
        reward = self.register().json()['registration_reward']
        self.assertEqual((reward['points'], reward['personality_cost'], reward['imaging_cost']), (35, 15, 8))
