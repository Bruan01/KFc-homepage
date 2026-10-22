from urllib.parse import quote

from django.test import TestCase

from .models import OfficialCommunitySettings, User


class PublicOfficialIdentityTests(TestCase):
    def test_unconfigured_identity_is_public_and_empty(self):
        response = self.client.get("/api/community/official")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"account": None})

    def test_only_public_identity_is_returned(self):
        user = User.objects.create(username="小k & friends", display_name="小 K", email="private@example.com", created_at="2026-10-22")
        OfficialCommunitySettings.objects.create(account=user, target_follower_count=1234, updated_by="private-admin")
        response = self.client.get("/api/community/official")
        self.assertEqual(response.json(), {"account": {"username": user.username, "display_name": "小 K", "profile_url": "/forum/user/" + quote(user.username, safe="")}})
        self.assertIn("no-store", response["Cache-Control"])
        for private in ["private@example.com", "target_follower_count", "updated_by", "private-admin", "api_key"]:
            self.assertNotIn(private, response.content.decode())

    def test_switching_config_changes_the_destination(self):
        first = User.objects.create(username="old-official", created_at="2026-10-22")
        second = User.objects.create(username="new-official", created_at="2026-10-22")
        config = OfficialCommunitySettings.objects.create(account=first)
        self.assertEqual(self.client.get("/api/community/official").json()["account"]["username"], first.username)
        config.account = second
        config.save(update_fields=["account"])
        self.assertEqual(self.client.get("/api/community/official").json()["account"]["username"], second.username)

    def test_system_generated_account_is_not_published(self):
        user = User.objects.create(username="virtual-official", is_system_generated=True, created_at="2026-10-22")
        OfficialCommunitySettings.objects.create(account=user)
        self.assertIsNone(self.client.get("/api/community/official").json()["account"])
