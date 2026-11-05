from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from types import SimpleNamespace
from unittest.mock import patch

from .middleware import HTMLCacheMiddleware


@override_settings(DEBUG=False, HTML_EDGE_CACHE_SECONDS=300)
class HTMLCachePolicyTests(SimpleTestCase):
    def render(self, response):
        return HTMLCacheMiddleware(lambda request: response)(RequestFactory().get('/personality/test'))

    def test_private_and_no_store_are_preserved(self):
        for policy in ('private, no-store', 'no-store', 'private, max-age=30', 'no-cache'):
            with self.subTest(policy=policy):
                response = self.render(HttpResponse('protected', headers={'Cache-Control': policy}))
                self.assertEqual(response['Cache-Control'], policy)
                self.assertIn('Cookie', response['Vary'])

    def test_cookies_are_detected_before_header_serialization(self):
        response = HttpResponse('page')
        response.set_cookie('csrftoken', 'test-cookie')
        self.assertFalse(response.has_header('Set-Cookie'))
        response = self.render(response)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertIn('Cookie', response['Vary'])

    def test_public_shell_stays_cacheable(self):
        response = self.render(HttpResponse('public shell'))
        self.assertIn('s-maxage=300', response['Cache-Control'])
        self.assertEqual(response['Vary'], 'Accept-Encoding')

    def test_admin_page_and_guest_redirect_are_not_shared(self):
        from . import pages
        for admin in (None, {"username": "admin", "admin_level": 3, "is_super": True}):
            with self.subTest(admin=bool(admin)), patch.object(pages, 'get_admin_context', return_value=admin):
                request = RequestFactory().get('/admin/users')
                response = HTMLCacheMiddleware(lambda req: pages.page(req, page_path='admin/users'))(request)
                self.assertEqual(response.status_code, 200 if admin else 302)
                self.assertEqual(response['Cache-Control'], 'private, no-store')
                response.close()

    @override_settings(HTTPS_REQUIRED=True)
    def test_imaging_personalized_template_is_private_and_upgrades_http(self):
        from apps.imaging.views import studio_page
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                request = RequestFactory().get('/imaging')
                request.user = SimpleNamespace(is_authenticated=authenticated, username='preview')
                response = studio_page(request)
                self.assertEqual(response['Cache-Control'], 'private, no-store')
                self.assertContains(response, 'data-kflow-https')
