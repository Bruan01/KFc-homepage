import json
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import User
from apps.personality.models import Assessment
from apps.personality.operations import notify_report_completed
from .models import Achievement, UserAchievement, UserStats
from .personality_badges import sync_personality_badges
from .services import badges_payload


class PersonalityBadgeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="explorer", password="pass1234")
        self.other = User.objects.create_user(username="other", password="pass1234")
        self.client.force_login(self.user)

    def report(self, kind="INFP", **kwargs):
        return Assessment.objects.create(user=self.user, status="completed", report={"type": kind}, **kwargs)

    def test_completed_report_notification_grants_once_and_never_auto_equips(self):
        row = self.report()
        with patch("apps.personality.provider.complete_json") as model:
            self.assertTrue(notify_report_completed(row))
            self.assertTrue(notify_report_completed(row))
        model.assert_not_called()
        self.assertEqual(UserAchievement.objects.filter(user=self.user).count(), 1)
        self.assertFalse(UserStats.objects.filter(user=self.user, showcase__isnull=False).exists())
        self.assertEqual(badges_payload(self.user, include_private=False), [])

    def test_owner_backfill_only_keeps_latest_completed_type(self):
        self.report("INFP"); self.report("ENFP"); self.report("ENFP")
        Assessment.objects.create(user=self.user, status="failed", report={"type": "ENTJ"})
        Assessment.objects.create(user=self.other, status="completed", report={"type": "ISTP"})
        for _ in range(2): self.client.get("/api/achievements")
        self.assertEqual(set(UserAchievement.objects.filter(user=self.user).values_list("achievement__code", flat=True)), {"mbti-enfp"})
        self.assertFalse(UserAchievement.objects.filter(user=self.other).exists())

    def test_only_owned_type_can_be_worn_and_only_worn_type_is_public(self):
        call_command("seed_achievements", verbosity=0)
        self.report("ENFP"); self.report("INFP")
        post = lambda code: self.client.post("/api/achievements/showcase", json.dumps({"code": code}), content_type="application/json")
        self.assertEqual(post("mbti-intj").status_code, 403)
        self.assertEqual(post("mbti-infp").status_code, 200)
        self.assertEqual([b["code"] for b in badges_payload(self.user, include_private=False)], ["mbti-infp"])
        self.assertEqual(len(badges_payload(self.user)), 1)
        self.client.force_login(self.other)
        public = self.client.get('/api/forum/users/explorer').json()['profile']['badges']
        self.assertEqual([b['code'] for b in public], ['mbti-infp'])
        self.client.force_login(self.user)
        self.assertEqual(post("").status_code, 200)
        self.assertEqual(badges_payload(self.user, include_private=False), [])

    def test_new_result_replaces_worn_type_and_old_type_cannot_be_equipped(self):
        self.report("INFP")
        sync_personality_badges(self.user)
        old = Achievement.objects.get(code="mbti-infp")
        UserStats.objects.create(user=self.user, showcase=old)
        self.report("ENFP")
        endpoint = "/api/achievements/showcase"
        response = self.client.post(endpoint, json.dumps({"code": "mbti-infp"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserStats.objects.get(user=self.user).showcase.code, "mbti-enfp")
        self.assertEqual([b["code"] for b in badges_payload(self.user)], ["mbti-enfp"])

    def test_retesting_does_not_replace_other_community_badges(self):
        community = Achievement.objects.create(code="first-post", name="初来乍到")
        UserAchievement.objects.create(user=self.user, achievement=community)
        UserStats.objects.create(user=self.user, showcase=community)
        self.report("INFP")
        sync_personality_badges(self.user)
        self.assertEqual(UserStats.objects.get(user=self.user).showcase, community)
        self.assertTrue(UserAchievement.objects.filter(user=self.user, achievement=community).exists())

    def test_older_report_finishing_late_cannot_replace_newer_result(self):
        older = self.report("INFP", created_at="2026-11-01T00:00:00+00:00")
        self.report("ENFP", created_at="2026-11-02T00:00:00+00:00")
        notify_report_completed(older)
        self.assertEqual([b["code"] for b in badges_payload(self.user)], ["mbti-enfp"])

    def test_same_timestamp_uses_creation_order_instead_of_random_uuid_order(self):
        self.report("INFP", id="ffffffff-ffff-4fff-8fff-ffffffffffff", created_at="2026-11-02T10:00:00+00:00")
        self.report("ENFP", id="00000000-0000-4000-8000-000000000001", created_at="2026-11-02T10:00:00+00:00")
        sync_personality_badges(self.user)
        self.assertEqual([b["code"] for b in badges_payload(self.user)], ["mbti-enfp"])

    def test_seed_cleans_up_old_multiple_grants_and_invalid_latest_type_does_not_fall_back(self):
        call_command("seed_achievements", verbosity=0)
        self.report("INFP")
        self.report("ENFP")
        for code in ["mbti-infp", "mbti-enfp"]:
            UserAchievement.objects.create(user=self.user, achievement=Achievement.objects.get(code=code))
        call_command("seed_achievements", verbosity=0)
        self.assertEqual([b["code"] for b in badges_payload(self.user)], ["mbti-enfp"])
        self.report(["INTJ"])
        sync_personality_badges(self.user)
        self.assertEqual(badges_payload(self.user), [])

    def test_seed_has_sixteen_equal_tier_badges_and_is_idempotent(self):
        for _ in range(2): call_command("seed_achievements", verbosity=0)
        badges = Achievement.objects.filter(code__startswith="mbti-")
        self.assertEqual(badges.count(), 16)
        self.assertEqual(set(badges.values_list("tier", flat=True)), {"identity"})
        self.assertEqual(set(badges.values_list("category", flat=True)), {"personality"})

    def test_anonymous_catalog_never_grants_and_disabled_badge_stays_disabled(self):
        self.report()
        badge = Achievement.objects.create(code="mbti-infp", name="INFP", is_active=False)
        self.client.logout()
        self.client.get("/api/achievements")
        sync_personality_badges(self.user)
        self.assertFalse(UserAchievement.objects.filter(achievement=badge).exists())

    def test_report_claim_is_idempotent_and_directs_to_latest_type_without_auto_wearing(self):
        older = self.report("INFP", created_at="2026-11-01T00:00:00+00:00")
        self.report("ENFP", created_at="2026-11-02T00:00:00+00:00")
        with patch("apps.personality.provider.complete_json") as model:
            for _ in range(3):
                response = self.client.post('/api/achievements/personality/claim', json.dumps({'assessment_id':str(older.pk)}), content_type='application/json')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['badge']['code'], 'mbti-enfp')
                self.assertEqual(response.json()['redirect'], '/achievements?badge=mbti-enfp#personality-badges')
        model.assert_not_called()
        self.assertEqual(UserAchievement.objects.filter(user=self.user).count(), 1)
        self.assertFalse(UserStats.objects.filter(user=self.user, showcase__isnull=False).exists())

    def test_report_claim_rejects_other_owner_incomplete_and_invalid_ids(self):
        other = Assessment.objects.create(user=self.other, status='completed', report={'type':'INTJ'})
        unfinished = Assessment.objects.create(user=self.user, status='processing', report={'type':'INFP'})
        for assessment_id, status in [(str(other.pk),404),(str(unfinished.pk),404),('bad-id',400)]:
            response = self.client.post('/api/achievements/personality/claim', json.dumps({'assessment_id':assessment_id}), content_type='application/json')
            self.assertEqual(response.status_code, status)
        self.assertFalse(UserAchievement.objects.exists())
        self.client.logout()
        self.assertEqual(self.client.post('/api/achievements/personality/claim', json.dumps({'assessment_id':str(other.pk)}), content_type='application/json').status_code, 401)
