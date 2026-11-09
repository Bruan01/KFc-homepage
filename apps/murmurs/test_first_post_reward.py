from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import SystemSetting
from apps.points.models import PointAccount, PointLedger
from .models import Murmur


class FirstMurmurRewardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='first_murmur_user', password='test-password')
        self.client.force_login(self.user)

    def post(self, key='first-post-key-001', content='新鲜出炉的 INFP，来社区报个到。'):
        return self.client.post('/api/murmurs', {'content': content, 'client_key': key}, content_type='application/json')

    def allow_next_post(self):
        Murmur.objects.filter(author_username=self.user.username).update(created_at=(timezone.now()-timedelta(minutes=1)).isoformat())

    def test_first_post_receipt_and_idempotent_retry(self):
        offer = self.client.get('/api/murmurs/session').json()['first_post_reward']
        self.assertTrue(offer['eligible']); self.assertEqual(offer['points'], 10)
        response = self.post()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['first_post_reward']['points'], 10)
        self.assertEqual(response.json()['first_post_reward']['imaging_url'], '/imaging')
        retry = self.post()
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()['first_post_reward']['points'], 10)
        self.assertEqual(PointAccount.objects.get(user=self.user).balance, 10)
        self.assertEqual(PointLedger.objects.filter(user=self.user, event_type='murmur_first_post').count(), 1)
        self.assertFalse(self.client.get('/api/murmurs/session').json()['first_post_reward']['eligible'])
        self.allow_next_post()
        second = self.post('second-post-key-002')
        self.assertEqual(second.status_code, 201)
        self.assertIsNone(second.json()['first_post_reward'])
        self.assertEqual(PointAccount.objects.get(user=self.user).balance, 10)

    def test_historical_and_deleted_posts_are_not_first_posts(self):
        Murmur.objects.create(author_username=self.user.username, client_key='historical-post', content='旧内容', is_deleted=True,
                              created_at=(timezone.now()-timedelta(days=1)).isoformat())
        self.assertFalse(self.client.get('/api/murmurs/session').json()['first_post_reward']['eligible'])
        self.assertEqual(self.post().status_code, 201)
        self.assertFalse(PointLedger.objects.filter(user=self.user).exists())

    def test_deleting_awarded_post_does_not_reset_reward(self):
        self.assertEqual(self.post().status_code, 201)
        Murmur.objects.filter(author_username=self.user.username).delete()
        self.assertEqual(self.post('another-post-key').status_code, 201)
        self.assertEqual(PointLedger.objects.filter(user=self.user, event_type='murmur_first_post').count(), 1)
        self.assertEqual(PointAccount.objects.get(user=self.user).balance, 10)

    def test_configured_amount_and_zero_switch(self):
        SystemSetting.objects.create(setting_key='points.murmurs.first_post_reward', setting_value='20', updated_at='x', updated_by='test')
        self.assertEqual(self.post().json()['first_post_reward']['points'], 20)
        other = User.objects.create_user(username='reward_disabled', password='test-password')
        self.client.force_login(other)
        SystemSetting.objects.filter(setting_key='points.murmurs.first_post_reward').update(setting_value='0')
        self.assertFalse(self.client.get('/api/murmurs/session').json()['first_post_reward']['eligible'])
        self.assertIsNone(self.post().json()['first_post_reward'])
        self.assertFalse(PointLedger.objects.filter(user=other).exists())

    def test_system_generated_and_frozen_accounts_are_not_rewarded(self):
        User.objects.filter(pk=self.user.pk).update(is_system_generated=True)
        self.assertFalse(self.client.get('/api/murmurs/session').json()['first_post_reward']['eligible'])
        self.assertEqual(self.post().status_code, 201)
        self.assertFalse(PointLedger.objects.filter(user=self.user).exists())
        self.allow_next_post()
        other = User.objects.create_user(username='reward_frozen', password='test-password')
        PointAccount.objects.create(user=other, status='frozen', updated_at='x')
        self.client.force_login(other)
        self.assertFalse(self.client.get('/api/murmurs/session').json()['first_post_reward']['eligible'])
        self.assertEqual(self.post().status_code, 201)
        self.assertFalse(PointLedger.objects.filter(user=other).exists())

    def test_failed_post_rolls_back_points_and_ledger(self):
        with patch('apps.murmurs.views.enqueue_reply', side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError):
                self.post()
        self.assertFalse(Murmur.objects.filter(author_username=self.user.username).exists())
        self.assertFalse(PointLedger.objects.filter(user=self.user).exists())
        self.assertTrue(self.client.get('/api/murmurs/session').json()['first_post_reward']['eligible'])

    def test_invalid_submission_never_awards(self):
        self.assertEqual(self.post(content='').status_code, 400)
        self.assertFalse(PointLedger.objects.filter(user=self.user).exists())

    def test_reward_settings_use_existing_admin_permissions_and_validation(self):
        endpoint = '/api/admin/points/settings'
        self.assertEqual(self.client.post(endpoint, {'murmur_first_post_reward':25}, content_type='application/json').status_code, 401)
        session = self.client.session
        session.update({'admin_username':self.user.username, 'admin_level':2})
        session.save()
        self.assertEqual(self.client.post(endpoint, {'murmur_first_post_reward':25}, content_type='application/json').status_code, 403)
        session = self.client.session
        session.update({'admin_username':self.user.username, 'admin_level':3})
        session.save()
        response = self.client.post(endpoint, {'murmur_first_post_reward':25}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['item']['murmur_first_post_reward'], 25)
        self.assertEqual(self.client.post(endpoint, {'murmur_first_post_reward':-1}, content_type='application/json').status_code, 400)
        self.assertEqual(self.post().json()['first_post_reward']['points'], 25)
