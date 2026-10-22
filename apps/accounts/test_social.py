import json

from django.db import IntegrityError, transaction
from django.test import Client, TestCase

from apps.murmurs.models import MurmurBlock
from .models import User, UserFollow


class FollowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create(username="alice", display_name="阿梨", created_at="2026-10-22")
        cls.bob = User.objects.create(username="bob", display_name="小波", created_at="2026-10-22")

    def setUp(self):
        self.client.force_login(self.alice)

    def follow(self, name="bob", client=None):
        return (client or self.client).post(f"/api/users/{name}/follow", "{}", content_type="application/json")

    def test_follow_unfollow_are_idempotent_with_correct_counts(self):
        for _ in range(2):
            response = self.follow()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["is_following"])
            self.assertEqual(response.json()["follower_count"], 1)
        self.assertEqual(UserFollow.objects.count(), 1)
        own = self.client.get("/api/users/alice/social").json()
        self.assertEqual(own["following_count"], 1)
        bob = Client(); bob.force_login(self.bob)
        self.assertTrue(bob.get("/api/users/alice/social").json()["follows_you"])
        for _ in range(2):
            response = self.client.delete("/api/users/bob/follow")
            self.assertFalse(response.json()["is_following"])
            self.assertEqual(response.json()["follower_count"], 0)

    def test_authentication_csrf_self_and_missing_user(self):
        self.assertEqual(self.follow(client=Client()).status_code, 401)
        self.assertEqual(Client().get("/api/users/mentions").status_code, 401)
        self.assertEqual(self.follow("alice").status_code, 400)
        self.assertEqual(self.follow("missing").status_code, 404)
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.alice)
        self.assertEqual(self.follow(client=strict).status_code, 403)
        token = strict.get("/murmurs").cookies["csrftoken"].value
        self.assertEqual(strict.post("/api/users/bob/follow", HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_blocks_in_both_directions_prevent_follow_and_mention_search(self):
        self.follow()
        for blocker, blocked in [("alice", "bob"), ("bob", "alice")]:
            with self.subTest(blocker=blocker):
                MurmurBlock.objects.all().delete()
                MurmurBlock.objects.create(username=blocker, blocked_username=blocked)
                self.assertEqual(self.follow().status_code, 403)
                self.assertEqual(self.client.get("/api/users/mentions").json()["items"], [])
                self.assertEqual(self.client.delete("/api/users/bob/follow").status_code, 200)

    def test_lists_search_and_pagination_only_expose_public_fields(self):
        self.follow()
        self.assertEqual(self.client.get("/api/users/mentions?q=小波").json()["items"][0]["username"], "bob")
        self.assertEqual(self.client.get("/api/users/mentions?q=alice").json()["items"], [])
        bob = Client(); bob.force_login(self.bob)
        follower = bob.get("/api/users/bob/followers").json()["items"][0]
        self.assertEqual(follower["username"], "alice")
        self.assertNotIn("email", follower)
        self.assertNotIn("password", follower)
        users = User.objects.bulk_create([User(username=f"person{i}", created_at="2026-10-22") for i in range(23)])
        UserFollow.objects.bulk_create([UserFollow(follower=self.alice, following=user, created_at="2026-10-22") for user in users])
        first = self.client.get("/api/users/alice/following").json()
        second = self.client.get(f'/api/users/alice/following?after={first["next_cursor"]}').json()
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(len(second["items"]), 4)
        self.assertFalse({u["username"] for u in first["items"]} & {u["username"] for u in second["items"]})
        self.assertEqual(self.client.get("/api/users/alice/following?after=bad").status_code, 400)

    def test_connection_lists_are_only_visible_to_owner_even_for_admins(self):
        self.follow()
        for kind in ("followers", "following"):
            url = f"/api/users/bob/{kind}"
            self.assertEqual(Client().get(url).status_code, 401)
            self.assertEqual(self.client.get(url).status_code, 403)
            admin = Client(); session = admin.session
            session["admin_username"] = "root"; session["admin_is_super"] = True; session["admin_level"] = 3; session.save()
            self.assertEqual(admin.get(url).status_code, 403)
        public = Client().get("/api/users/bob/social").json()
        self.assertEqual(public["follower_count"], 1)
        self.assertFalse(public["can_view_connections"])
        self.assertTrue(self.client.get("/api/users/alice/social").json()["can_view_connections"])
        self.assertEqual(self.client.get("/api/users/mentions").json()["items"][0]["username"], "bob")

    def test_database_constraints_reject_duplicate_and_self_follows(self):
        self.follow()
        for target in (self.alice, self.bob):
            with self.subTest(target=target.username), self.assertRaises(IntegrityError), transaction.atomic():
                UserFollow.objects.create(follower=self.alice, following=target, created_at="2026-10-22")
