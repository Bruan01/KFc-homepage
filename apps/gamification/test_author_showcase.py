"""Worn badges follow author identities through public and live write paths."""
import json

from django.test import TestCase

from apps.accounts.models import User
from apps.forum.models import ForumCategory, ForumReply, ForumTopic
from apps.murmurs.models import Murmur, MurmurComment
from .models import Achievement, UserAchievement, UserStats
from .services import showcases_payload


class AuthorShowcaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username="badge_author", password="test-password")
        cls.badge = Achievement.objects.create(code="author-showcase", name="创作达人", icon="pen", tier="gold")
        UserAchievement.objects.create(user=cls.author, achievement=cls.badge)
        UserStats.objects.create(user=cls.author, showcase=cls.badge)
        cls.category = ForumCategory.objects.create(slug="badge-test", name="测试")
        cls.topic = ForumTopic.objects.create(category=cls.category, title="勋章文章", content="正文", author_username=cls.author.username)
        cls.reply = ForumReply.objects.create(topic=cls.topic, author_username=cls.author.username, content="回复")
        cls.post = Murmur.objects.create(author_username=cls.author.username, content="带勋章的日常", client_key="badge-post")
        cls.comment = MurmurComment.objects.create(murmur=cls.post, author_username=cls.author.username, content="评论", client_key="badge-comment")

    def assertBadge(self, author):
        self.assertEqual(author["showcase"], {
            "code": self.badge.code, "name": self.badge.name,
            "icon": self.badge.icon, "tier": "gold",
        })

    def test_forum_list_detail_and_incremental_replies(self):
        listing = self.client.get("/api/forum/topics").json()
        self.assertBadge(next(item for item in listing["items"] if item["id"] == self.topic.pk)["author_profile"])
        detail = self.client.get(f"/api/forum/topics/{self.topic.pk}").json()
        self.assertBadge(detail["topic"]["author_profile"])
        self.assertBadge(detail["topic"]["replies_detail"][0]["author_profile"])
        replies = self.client.get(f"/api/forum/topics/{self.topic.pk}/replies?after=0").json()
        self.assertBadge(replies["items"][0]["author_profile"])

    def test_new_forum_reply_includes_badge_before_refresh(self):
        self.client.force_login(self.author)
        response = self.client.post(f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "新回复"}), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertBadge(response.json()["reply"]["author_profile"])

    def test_murmur_list_detail_and_comments(self):
        listing = self.client.get("/api/murmurs").json()
        self.assertBadge(listing["items"][0]["author"])
        detail = self.client.get(f"/api/murmurs/{self.post.pk}").json()
        self.assertBadge(detail["item"]["author"])
        comments = self.client.get(f"/api/murmurs/{self.post.pk}/comments").json()
        self.assertBadge(comments["items"][0]["author"])

    def test_new_murmur_and_comment_include_badge_before_refresh(self):
        self.client.force_login(self.author)
        # The pre-existing fixture must not trip the normal posting cooldown.
        from django.utils import timezone
        from datetime import timedelta
        Murmur.objects.filter(pk=self.post.pk).update(created_at=(timezone.now() - timedelta(minutes=2)).isoformat())
        MurmurComment.objects.filter(pk=self.comment.pk).update(created_at=(timezone.now() - timedelta(minutes=2)).isoformat())
        post = self.client.post("/api/murmurs", json.dumps({"content": "新碎碎念", "client_key": "new-badge-post"}), content_type="application/json")
        self.assertEqual(post.status_code, 201, post.content)
        self.assertBadge(post.json()["item"]["author"])
        comment = self.client.post(f"/api/murmurs/{self.post.pk}/comments", json.dumps({"content": "新评论", "client_key": "new-badge-comment"}), content_type="application/json")
        self.assertEqual(comment.status_code, 201, comment.content)
        self.assertBadge(comment.json()["item"]["author"])

    def test_clear_badge_and_unknown_author_are_safe(self):
        from apps.forum.views import _authors_payload
        from apps.murmurs.services import authors_payload
        UserStats.objects.filter(user=self.author).update(showcase=None)
        for build in (_authors_payload, authors_payload):
            identities = build([self.author.username, "deleted-author"])
            self.assertIsNone(identities[self.author.username]["showcase"])
            self.assertIsNone(identities["deleted-author"]["showcase"])

    def test_badges_are_batched_for_many_authors(self):
        people = [User.objects.create_user(username=f"badge-person-{i}") for i in range(8)]
        UserStats.objects.bulk_create([UserStats(user=user, showcase=self.badge) for user in people])
        with self.assertNumQueries(1):
            badges = showcases_payload([user.username for user in people])
        self.assertEqual(len(badges), 8)
