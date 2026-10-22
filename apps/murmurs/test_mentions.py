import json
import uuid

from django.test import Client, TestCase

from apps.accounts.models import User, UserFollow
from apps.notifications.models import Notification
from .models import Murmur, MurmurBlock, MurmurComment


class MentionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create(username="alice", created_at="2026-10-22")
        cls.bob = User.objects.create(username="小波", created_at="2026-10-22")
        cls.carol = User.objects.create(username="carol", created_at="2026-10-22")

    def setUp(self):
        self.client.force_login(self.alice)
        UserFollow.objects.create(follower=self.alice, following=self.bob, created_at="2026-10-22")

    def send(self, content, url="/api/murmurs", key=None, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url, json.dumps({"content": content, "client_key": key or uuid.uuid4().hex, **extra}), content_type="application/json")

    def test_post_emoji_and_unicode_mention_roundtrip_deduplicate_and_replay(self):
        content = "今天好开心 👩🏽‍💻🥹❤️ @小波 一起庆祝！@小波 @carol @alice"
        response = self.send(content, key="mention-post-001")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["item"]["content"], content)
        row = Notification.objects.get(type="mention")
        self.assertEqual(row.recipient, self.bob)
        self.assertEqual(row.link, f'/murmurs?post={response.json()["item"]["id"]}#murmur-{response.json()["item"]["id"]}')
        self.assertEqual(self.send(content, key="mention-post-001").status_code, 200)
        self.assertEqual(Notification.objects.count(), 1)

    def test_comment_mention_has_exact_deep_link_and_no_duplicate_owner_alert(self):
        post = Murmur.objects.create(author_username="小波", content="hello", client_key="target-post")
        response = self.send("@小波 你好 👋", f"/api/murmurs/{post.pk}/comments", key="mention-comment-001")
        self.assertEqual(response.status_code, 201)
        notification = Notification.objects.get()
        self.assertEqual(notification.type, "mention")
        comment_id = response.json()["item"]["id"]
        self.assertEqual(notification.link, f"/murmurs?post={post.pk}&comment={comment_id}#murmur-comment-{comment_id}")
        self.assertEqual(self.send("@小波 你好 👋", f"/api/murmurs/{post.pk}/comments", key="mention-comment-001").status_code, 200)
        self.assertEqual(Notification.objects.count(), 1)

    def test_reply_mention_and_owner_each_receive_one_relevant_alert(self):
        post = Murmur.objects.create(author_username="carol", content="hello", client_key="reply-target")
        parent = MurmurComment.objects.create(murmur=post, author_username="小波", content="hi", client_key="parent-reply")
        response = self.send("@小波 收到啦", f"/api/murmurs/{post.pk}/comments", reply_to=parent.pk)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Notification.objects.filter(recipient=self.bob, type="mention").count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.carol, type="reply").count(), 1)
        self.assertEqual(Notification.objects.count(), 2)

    def test_unfollowing_removes_mention_permission(self):
        UserFollow.objects.all().delete()
        self.assertEqual(self.send("@小波 hey").status_code, 201)
        self.assertFalse(Notification.objects.exists())

    def test_both_block_directions_suppress_mentions(self):
        for blocker, blocked in [("alice", "小波"), ("小波", "alice")]:
            MurmurBlock.objects.all().delete(); Murmur.objects.all().delete()
            MurmurBlock.objects.create(username=blocker, blocked_username=blocked)
            self.assertEqual(self.send("@小波 hey").status_code, 201)
            self.assertFalse(Notification.objects.exists())

    def test_email_and_partial_username_do_not_mention(self):
        self.assertEqual(self.send("mail@小波 文字@小波 @小波extra").status_code, 201)
        self.assertFalse(Notification.objects.exists())

    def test_legacy_username_with_spaces_can_be_selected_using_braces(self):
        user = User.objects.create(username="old user.name", created_at="2026-10-22")
        UserFollow.objects.create(follower=self.alice, following=user, created_at="2026-10-22")
        self.assertEqual(self.send("你好 @{old user.name} 👋").status_code, 201)
        self.assertEqual(Notification.objects.get().recipient, user)

    def test_deep_link_loads_comment_after_first_page_and_respects_visibility(self):
        post = Murmur.objects.create(author_username="alice", content="target", client_key="deep-post")
        rows = MurmurComment.objects.bulk_create([MurmurComment(murmur=post, author_username="小波", content=str(i), client_key=f"deep-comment-{i}") for i in range(65)])
        url = f"/api/murmurs/{post.pk}/comments?target={rows[51].pk}"
        data = self.client.get(url).json()
        self.assertTrue(data["target_found"])
        self.assertIn(rows[51].pk, [row["id"] for row in data["items"]])
        foreign = Murmur.objects.create(author_username="alice", content="other", client_key="other-post")
        foreign_comment = MurmurComment.objects.create(murmur=foreign, author_username="小波", content="other", client_key="other-comment")
        self.assertFalse(self.client.get(f"/api/murmurs/{post.pk}/comments?target={foreign_comment.pk}").json()["target_found"])
        MurmurComment.objects.filter(pk=rows[51].pk).update(is_deleted=True)
        self.assertFalse(self.client.get(url).json()["target_found"])
        MurmurBlock.objects.create(username="alice", blocked_username="小波")
        self.assertEqual(self.client.get(url).json()["items"], [])
        self.assertEqual(self.client.get(f"/api/murmurs/{post.pk}/comments?target=bad").status_code, 400)
