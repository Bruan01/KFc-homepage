import json

from django.test import TestCase

from .models import Murmur, MurmurAppeal, MurmurFeature, MurmurReport


class ModerationQueueTests(TestCase):
    def setUp(self):
        session = self.client.session
        session.update({'admin_username': 'reviewer', 'admin_level': 2})
        session.save()
        self.expected = []
        for i in range(42):
            post = Murmur.objects.create(author_username='author', content=f'内容 {i}', client_key=f'review-{i}')
            kind = ('reports', 'appeals', 'features')[i % 3]
            # Dates deliberately do not follow IDs; equal timestamps cross queues.
            created = f'2026-11-{i % 9 + 1:02}T10:00:00+00:00'
            if kind == 'reports':
                row = MurmurReport.objects.create(murmur=post, target_key=f'post:{post.pk}', reporter_username='reader', reason='other', created_at=created, status='resolved' if i % 2 else 'pending')
            elif kind == 'appeals':
                row = MurmurAppeal.objects.create(murmur=post, target_key=f'post:{post.pk}', appellant_username='author', reason='请复核', created_at=created, status='accepted' if i % 2 else 'pending')
            else:
                row = MurmurFeature.objects.create(murmur=post, requested_by='author', created_at=created, status='approved' if i % 2 else 'pending')
            self.expected.append((created, kind, row.pk))

    def test_all_types_and_statuses_paginate_without_skips_or_duplicates(self):
        items, params = [], {}
        for _ in range(5):
            response = self.client.get('/api/admin/murmurs/moderation', params)
            self.assertEqual(response.status_code, 200, response.content)
            data = response.json()
            items.extend(data['items'])
            if not data['next_cursor']:
                break
            params['before'] = data['next_cursor']
        self.assertEqual([(item['created_at'], item['moderation_kind'], item['id']) for item in items], sorted(self.expected, reverse=True))
        self.assertEqual({item['moderation_kind'] for item in items}, {'reports', 'appeals', 'features'})

    def test_queue_specific_statuses_and_pending(self):
        for status, kind in [('approved', 'features'), ('accepted', 'appeals'), ('resolved', 'reports')]:
            items = self.client.get('/api/admin/murmurs/moderation', {'status': status}).json()['items']
            self.assertTrue(items)
            self.assertTrue(all(item['moderation_kind'] == kind and item['status'] == status for item in items))
        items = self.client.get('/api/admin/murmurs/moderation', {'status': 'pending'}).json()['items']
        self.assertEqual(len(items), 21)

    def test_invalid_input_and_permissions(self):
        for params in [{'status': 'unknown'}, {'before': '{}'}, {'before': json.dumps(['date', [], 1])}, {'before': json.dumps(['date', 'reports', True])}]:
            self.assertEqual(self.client.get('/api/admin/murmurs/moderation', params).status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.get('/api/admin/murmurs/moderation').status_code, 401)
        session = self.client.session
        session.update({'admin_username': 'junior', 'admin_level': 1})
        session.save()
        self.assertEqual(self.client.get('/api/admin/murmurs/moderation').status_code, 403)
