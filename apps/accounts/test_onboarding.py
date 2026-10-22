import json
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase, override_settings

from .models import GuideOnboarding, User


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class GuideOnboardingTests(TestCase):
    endpoint = "/api/user/guide-onboarding"

    def setUp(self):
        self.user = User.objects.create_user(username="guide-alice", password="guide-password-2026", created_at="2026-10-01T00:00:00+00:00")
        self.client.force_login(self.user)

    def post(self, action, **extra):
        return self.client.post(self.endpoint, {"action": action, **extra}, content_type="application/json")

    def enroll(self, state="pending"):
        return GuideOnboarding.objects.create(user=self.user, state=state, updated_at="2026-10-22T00:00:00+00:00")

    def register(self, **extra):
        self.client.logout()
        payload = {"username": "guide-new", "email": "guide-new@example.com", "password": "guide-password-2026", "code": "123456", **extra}
        with patch("apps.accounts.views.consume_verification_code", return_value=None):
            response = self.client.post("/api/user/register", payload, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return User.objects.get(username=payload["username"])

    def test_existing_users_are_not_enrolled_by_update_or_login(self):
        self.assertFalse(self.client.get(self.endpoint).json()["should_prompt"])
        self.assertFalse(self.post("shown").json()["claimed"])
        self.post("dismissed")
        self.assertFalse(GuideOnboarding.objects.filter(user=self.user).exists())

    def test_new_registration_is_enrolled(self):
        user = self.register()
        self.assertEqual(GuideOnboarding.objects.get(user=user).state, "pending")
        self.assertTrue(self.client.get(self.endpoint).json()["should_prompt"])

    def test_registration_carries_actual_visitor_guide_visit(self):
        user = self.register(guide_visited=True)
        self.assertEqual(GuideOnboarding.objects.get(user=user).state, "visited")
        self.assertFalse(self.client.get(self.endpoint).json()["should_prompt"])

    def test_non_boolean_visit_claim_does_not_skip_invitation(self):
        user = self.register(guide_visited="false")
        self.assertEqual(GuideOnboarding.objects.get(user=user).state, "pending")

    def test_failed_registration_does_not_enroll(self):
        with patch("apps.accounts.views.consume_verification_code", return_value="invalid verification code"):
            response = self.client.post("/api/user/register", {"username": "guide-failed", "email": "failed@example.com", "password": "guide-password-2026", "code": "000000"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(GuideOnboarding.objects.exists())

    def test_only_one_tab_can_claim_and_reload_does_not_repeat(self):
        self.enroll()
        self.assertTrue(self.post("shown").json()["claimed"])
        self.assertFalse(self.post("shown").json()["claimed"])
        self.assertFalse(self.client.get(self.endpoint).json()["should_prompt"])

    def test_dismissal_is_saved_for_other_devices(self):
        self.enroll()
        self.post("shown")
        self.post("dismissed")
        another_device = Client()
        another_device.force_login(self.user)
        self.assertEqual(another_device.get(self.endpoint).json()["state"], "dismissed")
        self.assertFalse(another_device.get(self.endpoint).json()["should_prompt"])

    def test_visit_wins_over_late_dismiss_or_claim(self):
        self.enroll()
        self.post("visited")
        self.post("dismissed")
        self.assertFalse(self.post("shown").json()["claimed"])
        self.assertEqual(self.client.get(self.endpoint).json()["state"], "visited")

    def test_visit_can_be_saved_for_existing_account_without_creating_prompt(self):
        self.post("visited")
        self.assertEqual(GuideOnboarding.objects.get(user=self.user).state, "visited")

    def test_request_cannot_modify_other_accounts(self):
        other = User.objects.create_user(username="guide-bob", password="guide-password-2026", created_at="2026-10-01")
        target = GuideOnboarding.objects.create(user=other, state="pending", updated_at="2026-10-01")
        self.post("visited", user_id=other.pk, username=other.username)
        target.refresh_from_db()
        self.assertEqual(target.state, "pending")

    def test_authentication_csrf_and_invalid_payloads(self):
        self.enroll()
        self.assertEqual(Client().get(self.endpoint).status_code, 401)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.endpoint, {"action": "visited"}, content_type="application/json").status_code, 403)
        csrf_client.get("/guide")
        token = csrf_client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(csrf_client.post(self.endpoint, {"action": "visited"}, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 200)
        for payload in [{}, {"action": []}, {"action": "pending"}, [], "bad json"]:
            response = self.client.post(self.endpoint, payload if isinstance(payload, str) else json.dumps(payload), content_type="application/json")
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.client.put(self.endpoint).status_code, 405)
        self.assertIn("no-store", self.client.get(self.endpoint)["Cache-Control"])

    def test_public_guide_keeps_old_anchors_and_has_matching_sections(self):
        from html.parser import HTMLParser

        class GuideParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.steps, self.navs, self.completions = [], [], []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                for key, collection in [("data-guide-step", self.steps), ("data-guide-nav", self.navs), ("data-guide-complete", self.completions)]:
                    if key in attrs:
                        collection.append(attrs[key])

        response = Client().get("/guide")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        parser = GuideParser()
        parser.feed(body)
        self.assertEqual(len(parser.steps), 11)
        self.assertEqual(parser.steps, parser.navs)
        self.assertEqual(parser.steps, parser.completions)
        for old in ["community", "identity", "discovery", "learning", "creating", "products", "benefits", "growth", "service"]:
            self.assertIn(old, parser.steps)
        self.assertIn('href="/murmurs"', body)
        self.assertIn('src="/guide-onboarding.js?v=', body)
