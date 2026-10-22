"""Pinning permissions, atomic audit records, filtering and feed pagination."""
import json
from unittest.mock import patch

from django.test import Client, TestCase

from apps.accounts.models import AdminAccount, User
from apps.forum.models import ForumCategory, ForumModerationAction, ForumTopic
from apps.murmurs.models import Murmur, MurmurBlock


class CommunityPinningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ForumTopic.objects.all().delete()
        cls.author = User.objects.create_user(username="pin-author")
        cls.other = User.objects.create_user(username="pin-other")
        cls.moderator = User.objects.create_user(username="pin-moderator")
        cls.admins = []
        for level, is_super in [(1, False), (2, False), (3, False), (3, True)]:
            user = User.objects.create_user(username=f"pin-admin-{level}-{is_super}")
            AdminAccount.objects.create(username=user.username, admin_level=level, is_super=is_super,
                                        password_hash=user.password, created_at="2026-10-22T00:00:00Z")
            cls.admins.append(user)
        cls.category = ForumCategory.objects.create(slug="pin-tests", name="Pin tests")
        cls.category.moderators.add(cls.moderator)
        cls.topic = ForumTopic.objects.create(category=cls.category, title="Pin topic", content="Content",
                                             author_username=cls.author.username)
        cls.post = Murmur.objects.create(author_username=cls.author.username, content="Pin post", client_key="pin-original")

    def endpoints(self):
        return [(f"/api/forum/topics/{self.topic.pk}/pin", self.topic),
                (f"/api/murmurs/{self.post.pk}/pin", self.post)]

    def send(self, url, desired=True, *, client=None):
        return (client or self.client).post(url, json.dumps({"pinned": desired}), content_type="application/json")

    def test_guests_authors_ordinary_users_l1_and_category_moderators_cannot_pin(self):
        for user in [None, self.author, self.other, self.admins[0], self.moderator]:
            client = Client()
            if user:
                client.force_login(user)
            for url, row in self.endpoints():
                with self.subTest(user=user, url=url):
                    response = self.send(url, client=client)
                    self.assertIn(response.status_code, [401, 403])
                    row.refresh_from_db()
                    self.assertFalse(row.is_pinned)

    def test_l2_l3_and_super_can_pin_other_users_content(self):
        for user in self.admins[1:]:
            self.client.force_login(user)
            for url, row in self.endpoints():
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.send(url).json()["pinned"], True)
                    row.refresh_from_db()
                    self.assertTrue(row.is_pinned)
                    self.assertEqual(self.send(url, False).json()["pinned"], False)
                    row.refresh_from_db()
                    self.assertFalse(row.is_pinned)

    def test_retry_is_idempotent_and_audits_only_changes(self):
        self.client.force_login(self.admins[1])
        for url, row in self.endpoints():
            for desired in [True, True, False, False]:
                self.assertEqual(self.send(url, desired).status_code, 200)
        logs = ForumModerationAction.objects.all()
        self.assertEqual(logs.count(), 4)
        self.assertEqual(set(logs.values_list("action", flat=True)),
                         {"topic_pinned", "topic_unpinned", "content_pinned", "content_unpinned"})
        self.assertEqual(set(logs.values_list("admin_username", flat=True)), {self.admins[1].username})

    def test_audit_failure_rolls_back_pin(self):
        self.client.force_login(self.admins[1])
        for url, row in self.endpoints():
            with patch.object(ForumModerationAction.objects, "create", side_effect=RuntimeError("audit failed")):
                with self.assertRaises(RuntimeError):
                    self.send(url)
            row.refresh_from_db()
            self.assertFalse(row.is_pinned)

    def test_boolean_is_required_and_malformed_json_rejected(self):
        self.client.force_login(self.admins[1])
        for url, row in self.endpoints():
            for body in [{}, {"pinned": 1}, {"pinned": 0}, {"pinned": "false"}, {"pinned": None}, [], "bad"]:
                with self.subTest(url=url, body=body):
                    self.assertEqual(self.client.post(url, json.dumps(body), content_type="application/json").status_code, 400)
            self.assertEqual(self.client.post(url, "{broken", content_type="application/json").status_code, 400)
            row.refresh_from_db()
            self.assertFalse(row.is_pinned)

    def test_csrf_is_required_and_get_cannot_mutate(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admins[1])
        for url, row in self.endpoints():
            self.assertEqual(self.send(url, client=client).status_code, 403)
            self.assertEqual(client.get(url).status_code, 405)
            token = client.get("/forum").cookies["csrftoken"].value
            self.assertEqual(client.post(url, json.dumps({"pinned": True}), content_type="application/json",
                                         HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_admin_console_session_is_supported(self):
        session = self.client.session
        session.update({"admin_username": "pin-console", "admin_level": 2, "admin_is_super": False})
        session.save()
        for url, row in self.endpoints():
            self.assertEqual(self.send(url).status_code, 200)

    def test_deleted_and_missing_targets_cannot_be_pinned(self):
        self.client.force_login(self.admins[1])
        self.topic.status = ForumTopic.STATUS_DELETED
        self.topic.save(update_fields=["status"])
        self.post.is_deleted = True
        self.post.save(update_fields=["is_deleted"])
        for url, row in self.endpoints():
            self.assertEqual(self.send(url).status_code, 404)
        for url in ["/api/forum/topics/99999999/pin", "/api/murmurs/99999999/pin"]:
            self.assertEqual(self.send(url).status_code, 404)

    def test_forum_pins_lead_latest_hot_featured_and_respect_filters(self):
        self.topic.is_pinned = self.topic.is_featured = True
        self.topic.save(update_fields=["is_pinned", "is_featured"])
        newer = ForumTopic.objects.create(category=self.category, title="New normal", content="Content",
                                         author_username=self.author.username, hot_score=99999, is_featured=True)
        for view in ["latest", "hot", "featured"]:
            items = self.client.get("/api/forum/topics", {"view": view}).json()["items"]
            self.assertEqual([item["id"] for item in items], [self.topic.pk, newer.pk])
            self.assertTrue(items[0]["pinned"])
        self.assertEqual(self.client.get("/api/forum/topics", {"q": "New normal"}).json()["items"][0]["id"], newer.pk)
        self.assertEqual(self.client.get("/api/forum/topics", {"category": "missing"}).json()["items"], [])

    def test_murmur_old_pin_does_not_skip_newer_normal_posts(self):
        self.post.is_pinned = True
        self.post.save(update_fields=["is_pinned"])
        normals = [Murmur.objects.create(author_username=self.author.username, content="normal", client_key=f"normal-{i}")
                   for i in range(24)]
        first = self.client.get("/api/murmurs").json()
        self.assertEqual(first["items"][0]["id"], self.post.pk)
        self.assertTrue(first["items"][0]["pinned"])
        second = self.client.get("/api/murmurs", {"before": first["next_cursor"]}).json()
        ids = [item["id"] for item in first["items"] + second["items"]]
        self.assertEqual(ids, [self.post.pk] + [row.pk for row in reversed(normals)])
        self.assertIsNone(second["next_cursor"])

    def test_murmur_cursor_crosses_full_pages_of_pins_without_duplicates(self):
        pins = [Murmur.objects.create(author_username=self.author.username, content="pin", client_key=f"p-{i}", is_pinned=True)
                for i in range(23)]
        normals = [Murmur.objects.create(author_username=self.author.username, content="normal", client_key=f"n-{i}")
                   for i in range(23)]
        first = self.client.get("/api/murmurs").json()
        self.assertTrue(first["next_cursor"].startswith("p:"))
        # Newly published normal content still appears after the remaining pins.
        new = Murmur.objects.create(author_username=self.author.username, content="new", client_key="new-during-pins")
        items = first["items"]
        cursor = first["next_cursor"]
        for _ in range(5):
            if cursor is None:
                break
            page = self.client.get("/api/murmurs", {"before": cursor}).json()
            items += page["items"]
            cursor = page["next_cursor"]
        self.assertIsNone(cursor)
        self.assertEqual([item["id"] for item in items],
                         [row.pk for row in reversed(pins)] + [new.pk] + [row.pk for row in reversed(normals)] + [self.post.pk])

    def test_murmur_pins_respect_author_mine_deleted_and_block_filters(self):
        self.post.is_pinned = True
        self.post.save(update_fields=["is_pinned"])
        other = Murmur.objects.create(author_username=self.other.username, content="other", client_key="other", is_pinned=True)
        deleted = Murmur.objects.create(author_username=self.other.username, content="deleted", client_key="deleted",
                                        is_pinned=True, is_deleted=True)
        self.client.force_login(self.author)
        MurmurBlock.objects.create(username=self.author.username, blocked_username=self.other.username)
        for params in [{}, {"scope": "mine"}, {"author": self.author.username}]:
            self.assertEqual([item["id"] for item in self.client.get("/api/murmurs", params).json()["items"]], [self.post.pk])
        self.assertEqual(self.client.get("/api/murmurs", {"author": self.other.username}).json()["items"], [])
        self.client.logout()
        ids = [item["id"] for item in self.client.get("/api/murmurs").json()["items"]]
        self.assertIn(other.pk, ids)
        self.assertNotIn(deleted.pk, ids)

    def test_invalid_murmur_pin_cursors_are_rejected(self):
        for cursor in ["p:", "p:0", "p:-1", "p:abc", "p:" + "9" * 19, "n:12"]:
            self.assertEqual(self.client.get("/api/murmurs", {"before": cursor}).status_code, 400)
