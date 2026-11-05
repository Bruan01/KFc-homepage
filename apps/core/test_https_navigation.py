from django.test import SimpleTestCase, override_settings

from . import pages


class HTTPSNavigationTests(SimpleTestCase):
    def render(self, filename):
        target = pages._safe_static_path(filename)
        return pages._rendered_html(target, pages._signature(target))

    @override_settings(HTTPS_REQUIRED=True)
    def test_production_guard_precedes_csrf_for_all_entry_points(self):
        for filename in ('index.html', 'user-login.html', 'personality/index.html', 'personality/test.html'):
            with self.subTest(filename=filename):
                html = self.render(filename)
                self.assertIn(b'data-kflow-https', html)
                self.assertLess(html.index(b'data-kflow-https'), html.index(b'/* /csrf.js */'))
                self.assertIn(b'location.replace(httpsUrl.href)', html)

    def test_configuration_change_invalidates_render_cache(self):
        with override_settings(HTTPS_REQUIRED=True):
            self.assertIn(b'data-kflow-https', self.render('user-login.html'))
        with override_settings(HTTPS_REQUIRED=False):
            self.assertNotIn(b'data-kflow-https', self.render('user-login.html'))

    @override_settings(HTTPS_REQUIRED=True)
    def test_all_shared_pages_have_https_guard(self):
        for filename in set(pages.PAGE_MAP.values()):
            with self.subTest(filename=filename):
                self.assertIn(b'data-kflow-https', self.render(filename))
