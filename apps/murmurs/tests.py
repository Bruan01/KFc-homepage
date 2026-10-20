"""Behavioral coverage of the new community feed; all data lives in the test DB."""
import json
import uuid
from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.forum.models import ForumImage, ForumModerationAction
from apps.notifications.models import Notification
from .models import Murmur, MurmurComment, MurmurImage, MurmurLike, MurmurReport


class MurmursTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="murmur_alice", password="test-password", display_name="阿梨", created_at="2026-01-01T00:00:00+00:00")
        cls.bob = User.objects.create_user(username="murmur_bob", password="test-password", created_at="2026-01-01T00:00:00+00:00")

    def setUp(self):
        self.client.force_login(self.alice)

    def post(self, **kwargs):
        data = {"author_username": self.alice.username, "content": "今天又写好了一点", "client_key": uuid.uuid4().hex}
        data.update(kwargs)
        return Murmur.objects.create(**data)

    def send(self, url="/api/murmurs", data=None, client=None, **kwargs):
        data = {"content": "随手分享一下", "client_key": uuid.uuid4().hex} if data is None else data
        return (client or self.client).post(url, json.dumps(data), content_type="application/json", **kwargs)

    def test_public_page_and_feed(self):
        self.post()
        guest = Client()
        page = guest.get("/murmurs")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "碎碎念")
        self.assertTrue(page.cookies.get("csrftoken"))
        self.assertEqual(len(guest.get("/api/murmurs").json()["items"]), 1)

    def test_login_required_for_writes(self):
        post = self.post()
        guest = Client()
        for url, data in [("/api/murmurs", {"content": "hello"}), (f"/api/murmurs/{post.pk}/like", {"liked": True}), (f"/api/murmurs/{post.pk}/comments", {"content": "hi"}), (f"/api/murmurs/{post.pk}/report", {"reason": "spam"}), ("/api/murmurs/blocks", {"username": self.bob.username})]:
            with self.subTest(url=url):
                self.assertEqual(self.send(url, data, client=guest).status_code, 401)

    def test_csrf_enforced(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.alice)
        self.assertEqual(self.send(client=strict).status_code, 403)
        token = strict.get("/murmurs").cookies["csrftoken"].value
        self.assertEqual(self.send(client=strict, HTTP_X_CSRFTOKEN=token).status_code, 201)

    def test_plain_text_post_and_self_payload(self):
        value = '<script>alert("hello")</script>\n**不解析 Markdown**'
        response = self.send(data={"content": value})
        self.assertEqual(response.status_code, 201)
        item = response.json()["item"]
        self.assertEqual(item["content"], value)
        self.assertTrue(item["is_own"])
        self.assertEqual(item["author"]["display_name"], "阿梨")
        self.assertEqual(Notification.objects.count(), 0)

    def test_image_only_and_order(self):
        images = [ForumImage.objects.create(uploader_username=self.alice.username, file=f"forum/test-{i}.webp", width=30, height=40) for i in range(3)]
        ids = [images[2].pk, images[0].pk, images[1].pk]
        response = self.send(data={"content": "", "images": ids})
        self.assertEqual(response.status_code, 201)
        self.assertEqual([i["id"] for i in response.json()["item"]["images"]], ids)

    def test_empty_oversized_and_malformed_payloads(self):
        invalid = [None, [], {"content": " "}, {"content": "字" * 1001}, {"content": []}, {"content": "ok", "images": [1] * 10}, {"content": "ok", "images": [True]}, {"content": "ok", "images": [1, 1]}, {"content": "ok", "images": "1"}, {"content": "ok", "client_key": "bad"}]
        for data in invalid:
            with self.subTest(data=str(data)[:50]):
                self.assertEqual(self.send(data=data if data is not None else {}, client=self.client).status_code, 400)
        self.assertEqual(self.client.post("/api/murmurs", "{bad", content_type="application/json").status_code, 400)
        self.assertEqual(Murmur.objects.count(), 0)

    def test_cannot_attach_someone_elses_or_missing_image(self):
        foreign = ForumImage.objects.create(uploader_username=self.bob.username, file="forum/other.webp")
        for ids in [[foreign.pk], [999999]]:
            self.assertEqual(self.send(data={"images": ids}).status_code, 400)

    def test_retry_is_idempotent_and_rate_limit_counts_deleted_posts(self):
        data = {"content": "记录", "client_key": "retry-operation-123"}
        first = self.send(data=data)
        second = self.send(data=data)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["item"]["id"], second.json()["item"]["id"])
        self.assertEqual(Murmur.objects.count(), 1)
        self.assertEqual(self.send(data={**data, "content": "不同的内容"}).status_code, 409)
        self.client.delete(f'/api/murmurs/{first.json()["item"]["id"]}')
        self.assertEqual(self.send().status_code, 429)
        self.assertEqual(self.send(data=data).status_code, 409)

    def test_feed_filters_and_cursor_are_stable_when_new_post_arrives(self):
        for i in range(24):
            self.post(author_username=self.bob.username, content=f"第{i}条")
        mine = self.post()
        deleted = self.post(is_deleted=True)
        first = self.client.get("/api/murmurs").json()
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(first["items"][0]["id"], mine.pk)
        self.assertNotIn(deleted.pk, [i["id"] for i in first["items"]])
        new = self.post()
        second = self.client.get(f'/api/murmurs?before={first["next_cursor"]}').json()
        ids = [i["id"] for i in first["items"] + second["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(new.pk, ids)
        self.assertEqual(len(self.client.get("/api/murmurs?scope=mine").json()["items"]), 2)
        self.assertEqual(len(self.client.get(f"/api/murmurs?author={self.bob.username}").json()["items"]), 20)
        for bad in ["bad", "-1", "99999999999999999999999999"]:
            self.assertEqual(self.client.get(f"/api/murmurs?before={bad}").status_code, 400)

    def test_like_is_idempotent_and_does_not_spam_notifications(self):
        post = self.post(author_username=self.bob.username)
        url = f"/api/murmurs/{post.pk}/like"
        with self.captureOnCommitCallbacks(execute=True):
            self.send(url, {"liked": True})
            self.send(url, {"liked": True})
        self.assertEqual(MurmurLike.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.bob, type="like").count(), 1)
        self.assertEqual(self.send(url, {"liked": False}).json()["like_count"], 0)
        with self.captureOnCommitCallbacks(execute=True):
            self.send(url, {"liked": True})
        self.assertEqual(Notification.objects.filter(recipient=self.bob, type="like").count(), 1)
        self.assertEqual(self.send(url, {"liked": "yes"}).status_code, 400)

    def test_no_self_notification(self):
        post = self.post()
        with self.captureOnCommitCallbacks(execute=True):
            self.send(f"/api/murmurs/{post.pk}/like", {"liked": True})
            self.send(f"/api/murmurs/{post.pk}/comments", {"content": "给自己留句话"})
        self.assertEqual(Notification.objects.count(), 0)

    def test_comment_retry_rate_limit_notification_and_delete(self):
        post = self.post(author_username=self.bob.username)
        url = f"/api/murmurs/{post.pk}/comments"
        data = {"content": "挺好", "client_key": "comment-request-123"}
        with self.captureOnCommitCallbacks(execute=True):
            first = self.send(url, data)
            repeat = self.send(url, data)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(MurmurComment.objects.count(), 1)
        notification = Notification.objects.get(type="reply")
        self.assertEqual(notification.link, f"/murmurs?post={post.pk}")
        self.assertEqual(self.send(url, {"content": "再写一条"}).status_code, 429)
        self.assertEqual(self.send(url, {**data, "content": "改过了"}).status_code, 409)
        comment_id = first.json()["item"]["id"]
        self.assertEqual(self.client.delete(f"/api/murmurs/comments/{comment_id}").json()["comment_count"], 0)
        self.assertEqual(self.client.get(url).json()["items"], [])

    def test_comments_validation_and_pagination(self):
        post = self.post()
        url = f"/api/murmurs/{post.pk}/comments"
        for content in [" ", "字" * 501, ["invalid"]]:
            self.assertEqual(self.send(url, {"content": content}).status_code, 400)
        for i in range(34):
            MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content=str(i), client_key=f"comment-key-{i}")
        first = self.client.get(url).json()
        self.assertEqual(len(first["items"]), 30)
        second = self.client.get(f'{url}?after={first["next_cursor"]}').json()
        self.assertEqual(len(second["items"]), 4)
        self.assertIsNone(second["next_cursor"])

    def test_ownership_and_soft_delete(self):
        post = self.post(author_username=self.bob.username)
        comment = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="hello", client_key="comment-other-key")
        self.assertEqual(self.client.delete(f"/api/murmurs/{post.pk}").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/murmurs/comments/{comment.pk}").status_code, 403)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.delete(f"/api/murmurs/{post.pk}").status_code, 200)
        post.refresh_from_db()
        self.assertTrue(post.is_deleted)
        for url in [f"/api/murmurs/{post.pk}", f"/api/murmurs/{post.pk}/comments"]:
            self.assertEqual(self.client.get(url).status_code, 404)
        for url, data in [(f"/api/murmurs/{post.pk}/like", {"liked": True}), (f"/api/murmurs/{post.pk}/comments", {"content": "hidden"}), (f"/api/murmurs/{post.pk}/report", {"reason": "spam"})]:
            self.assertEqual(self.send(url, data).status_code, 404)

    def test_blocks_hide_feed_details_comments_and_notifications(self):
        mine = self.post()
        other = self.post(author_username=self.bob.username)
        MurmurComment.objects.create(murmur=mine, author_username=self.bob.username, content="hidden", client_key="blocked-comment-key")
        self.assertEqual(self.send("/api/murmurs/blocks", {"username": self.bob.username}).status_code, 200)
        self.assertEqual([i["id"] for i in self.client.get("/api/murmurs").json()["items"]], [mine.pk])
        self.assertEqual(self.client.get(f"/api/murmurs/{other.pk}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/murmurs/{mine.pk}/comments").json()["items"], [])
        self.client.force_login(self.bob)
        with self.captureOnCommitCallbacks(execute=True):
            self.send(f"/api/murmurs/{mine.pk}/like", {"liked": True})
        self.assertEqual(Notification.objects.count(), 0)
        self.client.force_login(self.alice)
        self.assertEqual(len(self.client.get("/api/murmurs/blocks").json()["items"]), 1)
        self.client.delete("/api/murmurs/blocks", json.dumps({"username": self.bob.username}), content_type="application/json")
        self.assertEqual(len(self.client.get("/api/murmurs").json()["items"]), 2)
        self.assertEqual(self.send("/api/murmurs/blocks", {"username": self.alice.username}).status_code, 400)

    def test_report_deduplicates_and_admin_can_remove(self):
        post = self.post(author_username=self.bob.username)
        url = f"/api/murmurs/{post.pk}/report"
        self.assertEqual(self.send(url, {"reason": "spam", "details": "广告"}).status_code, 201)
        self.assertTrue(self.send(url, {"reason": "spam"}).json()["duplicate"])
        self.assertEqual(MurmurReport.objects.count(), 1)
        self.assertEqual(self.client.get("/api/admin/murmurs/reports").status_code, 401)
        self.become_admin(1)
        self.assertEqual(self.client.get("/api/admin/murmurs/reports").status_code, 403)
        self.become_admin(2)
        data = self.client.get("/api/admin/murmurs/reports").json()
        self.assertEqual(data["items"][0]["content"], post.content)
        review_url = f'/api/admin/murmurs/reports/{data["items"][0]["id"]}/review'
        response = self.send(review_url, {"decision": "resolved", "remove": True, "note": "核实后下线"})
        self.assertEqual(response.status_code, 200)
        post.refresh_from_db()
        self.assertTrue(post.is_deleted)
        self.assertEqual(ForumModerationAction.objects.get().target_type, "murmur")
        self.assertTrue(self.send(review_url, {"decision": "rejected"}).json()["replayed"])

    def become_admin(self, level):
        session = self.client.session
        session["admin_username"] = "murmur_reviewer"
        session["admin_level"] = level
        session["admin_is_super"] = False
        session.save()

    def test_admin_only_session_can_publish_and_moderate(self):
        self.client.logout()
        self.become_admin(2)
        self.assertTrue(self.client.get("/api/murmurs/session").json()["can_moderate"])
        self.assertEqual(self.send().status_code, 201)
        other = self.post(author_username=self.bob.username)
        self.assertEqual(self.client.delete(f"/api/murmurs/{other.pk}").status_code, 200)
        self.assertEqual(ForumModerationAction.objects.count(), 1)

    def test_comment_report_and_rejection_keep_content(self):
        post = self.post(author_username=self.bob.username)
        comment = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="需要审核", client_key="reported-comment")
        self.assertEqual(self.send(f"/api/murmurs/comments/{comment.pk}/report", {"reason": "abuse"}).status_code, 201)
        report = MurmurReport.objects.get()
        self.become_admin(2)
        self.assertEqual(self.send(f"/api/admin/murmurs/reports/{report.pk}/review", {"decision": "rejected", "remove": True}).status_code, 200)
        comment.refresh_from_db()
        self.assertFalse(comment.is_deleted)

    def test_feed_query_count_does_not_grow_with_authors_and_images(self):
        self.post()
        with CaptureQueriesContext(connection) as small:
            self.client.get("/api/murmurs")
        for i in range(18):
            post = self.post(author_username=self.bob.username)
            image = ForumImage.objects.create(uploader_username=self.bob.username, file=f"forum/query-{i}.webp")
            MurmurImage.objects.create(murmur=post, image=image)
        with CaptureQueriesContext(connection) as large:
            self.client.get("/api/murmurs")
        self.assertLessEqual(len(large), len(small) + 1)

    def test_feed_counts_likes_and_comments_independently(self):
        post = self.post()
        for i in range(3):
            MurmurLike.objects.create(murmur=post, username=f"liker-{i}")
        for i in range(5):
            MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="hi", client_key=f"count-comment-{i}", is_deleted=i == 4)
        item = self.client.get("/api/murmurs").json()["items"][0]
        self.assertEqual(item["like_count"], 3)
        self.assertEqual(item["comment_count"], 4)

    def test_comment_query_count_does_not_grow_with_rows(self):
        post = self.post()
        MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="hi", client_key="first-query-comment")
        with CaptureQueriesContext(connection) as small:
            self.client.get(f"/api/murmurs/{post.pk}/comments")
        for i in range(15):
            MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="hi", client_key=f"query-comment-{i}")
        with CaptureQueriesContext(connection) as large:
            self.client.get(f"/api/murmurs/{post.pk}/comments")
        self.assertLessEqual(len(large), len(small) + 1)
