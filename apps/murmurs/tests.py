"""Behavioral coverage of the new community feed; all data lives in the test DB."""
import json
import uuid
from io import BytesIO
from tempfile import TemporaryDirectory
from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.forum.models import ForumImage, ForumModerationAction
from apps.notifications.models import Notification
from .models import Murmur, MurmurBlock, MurmurComment, MurmurCommentImage, MurmurImage, MurmurLike, MurmurReport


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

    def test_image_only_comment_order_replay_and_notification(self):
        post = self.post(author_username=self.bob.username)
        images = [ForumImage.objects.create(uploader_username=self.alice.username, file=f"forum/reply-{i}.gif", width=32, height=40) for i in range(3)]
        ids = [images[2].pk, images[0].pk, images[1].pk]
        payload = {"content": "", "images": ids, "client_key": "image-comment-retry"}
        url = f"/api/murmurs/{post.pk}/comments"
        with self.captureOnCommitCallbacks(execute=True):
            response = self.send(url, payload)
            repeat = self.send(url, payload)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(repeat.status_code, 200)
        item = response.json()["item"]
        self.assertEqual(item["content"], "")
        self.assertEqual([i["id"] for i in item["images"]], ids)
        self.assertEqual(item["images"][0]["width"], 32)
        self.assertEqual(MurmurComment.objects.count(), 1)
        self.assertEqual(MurmurCommentImage.objects.count(), 3)
        self.assertEqual(Notification.objects.get(type="reply").body, "发送了图片或表情包")
        self.assertEqual(self.client.get(url).json()["items"][0]["images"], item["images"])
        self.assertEqual(self.send(url, {**payload, "images": list(reversed(ids))}).status_code, 409)

    def test_comment_emoji_and_image_validation(self):
        post = self.post()
        url = f"/api/murmurs/{post.pk}/comments"
        foreign = ForumImage.objects.create(uploader_username=self.bob.username, file="forum/foreign.gif")
        images = [ForumImage.objects.create(uploader_username=self.alice.username, file=f"forum/own-{i}.webp") for i in range(5)]
        invalid = [[foreign.pk], [999999], [True], [images[0].pk] * 2, [image.pk for image in images], "1", None]
        for ids in invalid:
            with self.subTest(images=ids):
                self.assertEqual(self.send(url, {"content": "😀", "images": ids}).status_code, 400)
        self.assertEqual(MurmurComment.objects.count(), 0)
        response = self.send(url, {"content": "太棒了 😂❤️🎉", "images": [image.pk for image in images[:4]]})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["item"]["content"], "太棒了 😂❤️🎉")
        self.assertEqual(len(response.json()["item"]["images"]), 4)

    def test_animated_gif_upload_can_be_sent_as_comment(self):
        from PIL import Image
        post = self.post()
        buffer = BytesIO()
        Image.new("RGB", (8, 8), "red").save(buffer, format="GIF", save_all=True,
            append_images=[Image.new("RGB", (8, 8), "blue")], duration=100, loop=0)
        original = buffer.getvalue()
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            response = self.client.post("/api/forum/images", {"file": SimpleUploadedFile("sticker.gif", original, content_type="image/gif")})
            self.assertEqual(response.status_code, 201, response.content)
            image_id = response.json()["image"]["id"]
            response = self.send(f"/api/murmurs/{post.pk}/comments", {"images": [image_id]})
            self.assertEqual(response.status_code, 201, response.content)
            image = ForumImage.objects.get(pk=image_id)
            with image.file.open("rb") as stored:
                self.assertEqual(stored.read(), original)
            self.assertEqual(image.content_type, "image/gif")

    def test_image_comment_report_can_be_reviewed_and_removed(self):
        post = self.post(author_username=self.bob.username)
        image = ForumImage.objects.create(uploader_username=self.alice.username, file="forum/reported.gif")
        response = self.send(f"/api/murmurs/{post.pk}/comments", {"images": [image.pk]})
        comment_id = response.json()["item"]["id"]
        self.send(f"/api/murmurs/comments/{comment_id}/report", {"reason": "spam"})
        self.become_admin(2)
        report = self.client.get("/api/admin/murmurs/reports").json()["items"][0]
        self.assertEqual(report["images"][0]["id"], image.pk)
        self.assertEqual(self.send(f'/api/admin/murmurs/reports/{report["id"]}/review', {"decision": "resolved", "remove": True}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/murmurs/{post.pk}/comments").json()["items"], [])
        self.assertEqual(ForumModerationAction.objects.get().target_type, "murmur_comment")

    def test_reply_to_comment_with_image_is_idempotent_and_notifies_both_authors(self):
        owner = User.objects.create_user(username="murmur_owner", password="test-password", created_at="x")
        post = self.post(author_username=owner.username)
        parent = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="原评论", client_key="reply-parent-key")
        image = ForumImage.objects.create(uploader_username=self.alice.username, file="forum/reply.gif")
        payload = {"content": "同意 😂", "images": [image.pk], "reply_to": parent.pk, "client_key": "reply-retry-operation"}
        url = f"/api/murmurs/{post.pk}/comments"
        with self.captureOnCommitCallbacks(execute=True):
            first = self.send(url, payload)
            repeated = self.send(url, payload)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(repeated.status_code, 200)
        item = first.json()["item"]
        self.assertEqual(item["reply_to"]["id"], parent.pk)
        self.assertEqual(item["reply_to"]["author"]["username"], self.bob.username)
        self.assertEqual(item["images"][0]["id"], image.pk)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertIn("回复了你的评论", Notification.objects.get(recipient=self.bob).title)
        self.assertEqual(self.client.get(url).json()["items"][-1]["reply_to"], item["reply_to"])
        self.assertEqual(self.send(url, {**payload, "reply_to": None}).status_code, 409)

    def test_reply_to_post_author_only_sends_one_notification(self):
        post = self.post(author_username=self.bob.username)
        parent = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="hi", client_key="same-author-parent")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.send(f"/api/murmurs/{post.pk}/comments", {"content": "回复", "reply_to": parent.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertIn("回复了你的评论", Notification.objects.get().title)

    def test_reply_notifications_respect_blocks_and_do_not_notify_self(self):
        post = self.post()
        parent = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="hi", client_key="notification-parent",
            created_at=(timezone.now() - timedelta(seconds=10)).isoformat())
        MurmurBlock.objects.create(username=self.bob.username, blocked_username=self.alice.username)
        url = f"/api/murmurs/{post.pk}/comments"
        with self.captureOnCommitCallbacks(execute=True):
            response = self.send(url, {"content": "reply", "reply_to": parent.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Notification.objects.count(), 0)
        MurmurBlock.objects.filter(username=self.bob.username, blocked_username=self.alice.username).delete()
        self.client.force_login(self.bob)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.send(url, {"content": "reply to myself", "reply_to": parent.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.get().recipient_id, self.alice.pk)

    def test_reply_target_must_be_visible_and_belong_to_same_post(self):
        post = self.post()
        other = self.post()
        foreign = MurmurComment.objects.create(murmur=other, author_username=self.bob.username, content="elsewhere", client_key="foreign-parent-key")
        deleted = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="deleted", client_key="deleted-parent-key", is_deleted=True)
        url = f"/api/murmurs/{post.pk}/comments"
        for target in [True, 0, -1, "1", [], {}]:
            with self.subTest(target=target):
                self.assertEqual(self.send(url, {"content": "reply", "reply_to": target}).status_code, 400)
        for target in [999999, foreign.pk, deleted.pk]:
            self.assertEqual(self.send(url, {"content": "reply", "reply_to": target}).status_code, 404)
        parent = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="hidden", client_key="blocked-parent-key")
        self.send("/api/murmurs/blocks", {"username": self.bob.username})
        self.assertEqual(self.send(url, {"content": "reply", "reply_to": parent.pk}).status_code, 404)
        self.assertEqual(MurmurComment.objects.count(), 3)

    def test_deleted_or_blocked_parent_does_not_leak_reply_context(self):
        post = self.post()
        parent = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="不要显示这段内容", client_key="hidden-context-parent")
        reply = MurmurComment.objects.create(murmur=post, reply_to=parent, author_username=self.alice.username, content="my reply", client_key="hidden-context-reply")
        url = f"/api/murmurs/{post.pk}/comments"
        self.send("/api/murmurs/blocks", {"username": self.bob.username})
        item = self.client.get(url).json()["items"][0]
        self.assertEqual(item["id"], reply.pk)
        self.assertEqual(item["reply_to"], {"id": parent.pk, "unavailable": True})
        self.client.delete("/api/murmurs/blocks", json.dumps({"username": self.bob.username}), content_type="application/json")
        parent.is_deleted = True
        parent.save(update_fields=["is_deleted"])
        self.assertEqual(self.client.get(url).json()["items"][0]["reply_to"], {"id": parent.pk, "unavailable": True})

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
        parent = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="hi", client_key="first-query-comment")
        with CaptureQueriesContext(connection) as small:
            self.client.get(f"/api/murmurs/{post.pk}/comments")
        for i in range(15):
            comment = MurmurComment.objects.create(murmur=post, reply_to=parent, author_username=self.bob.username, content="hi", client_key=f"query-comment-{i}")
            image = ForumImage.objects.create(uploader_username=self.bob.username, file=f"forum/comment-query-{i}.webp")
            MurmurCommentImage.objects.create(comment=comment, image=image)
        with CaptureQueriesContext(connection) as large:
            self.client.get(f"/api/murmurs/{post.pk}/comments")
        self.assertLessEqual(len(large), len(small) + 1)
