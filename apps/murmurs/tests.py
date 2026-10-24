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
from .models import Murmur, MurmurAppeal, MurmurBlock, MurmurComment, MurmurCommentImage, MurmurImage, MurmurLike, MurmurReport, MurmurVideo


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

    def test_pinned_post_survives_the_default_date_window(self):
        """日期分页只查「今天」，但置顶是公告：昨天的置顶必须浮现在第一页最前。"""
        today = timezone.localdate()
        inside = (today - timedelta(days=1)).isoformat() + "T16:00:00+00:00"
        outside = (today - timedelta(days=9)).isoformat() + "T04:00:00+00:00"
        older_normal = self.post(created_at=outside)
        pinned_old = self.post(author_username=self.bob.username, created_at=outside, is_pinned=True)
        fresh = self.post(created_at=inside)
        page_one = self.client.get("/api/murmurs?page=1").json()
        self.assertEqual([item["id"] for item in page_one["items"]], [pinned_old.pk, fresh.pk])
        self.assertNotIn(older_normal.pk, [item["id"] for item in page_one["items"]])
        self.assertEqual(page_one["total"], 1)
        self.assertEqual(page_one["total_pages"], 1)
        self.assertTrue(page_one["items"][0]["pinned"])
        # total/total_pages 只描述窗口内的量：置顶补位不会虚增页数。
        # 置顶优先级高于时间筛选：显式查历史档案时置顶同样浮现在第一页最前。
        window_only = self.client.get("/api/murmurs?page=1&start=2026-01-01&end=2026-01-01").json()
        self.assertEqual([item["id"] for item in window_only["items"]], [pinned_old.pk])
        self.assertEqual(window_only["total"], 0)
        self.assertEqual(window_only["total_pages"], 1)
        self.assertEqual(len(self.client.get("/api/murmurs?unread=1").json()["items"]), 0)
        # 窗口内本来就有置顶时，交给 -is_pinned 排序，不重复插入。
        pinned_new = self.post(created_at=inside, is_pinned=True)
        ids = [item["id"] for item in self.client.get("/api/murmurs?page=1").json()["items"]]
        self.assertEqual(ids, [pinned_new.pk, pinned_old.pk, fresh.pk])
        # 不带日期参数的游标分页保持原样：置顶在前，但昨天的普通帖依然可见。
        legacy = self.client.get("/api/murmurs").json()["items"]
        self.assertEqual(legacy[0]["id"], pinned_new.pk)
        self.assertIn(older_normal.pk, [item["id"] for item in legacy])

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
        # 打开评论区直接拿最新一页（第 5~34 条），更早的用 before 向上翻。
        first = self.client.get(url).json()
        self.assertEqual(len(first["items"]), 30)
        self.assertEqual([item["content"] for item in first["items"][:2]], ["4", "5"])
        self.assertIsNone(first["next_cursor"])
        second = self.client.get(f'{url}?before={first["older_cursor"]}').json()
        self.assertEqual([item["content"] for item in second["items"]], ["0", "1", "2", "3"])
        self.assertIsNone(second["older_cursor"])
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
        self.login_as(self.bob)
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

    def test_moderator_can_preview_deleted_post_but_members_cannot(self):
        post = self.post(author_username=self.bob.username)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.delete(f"/api/murmurs/{post.pk}").status_code, 200)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f"/api/murmurs/{post.pk}").status_code, 404)
        self.become_admin(1)
        self.assertEqual(self.client.get(f"/api/murmurs/{post.pk}").status_code, 404)
        self.become_admin(2)
        response = self.client.get(f"/api/murmurs/{post.pk}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["moderation_preview"])
        self.assertTrue(data["item"]["is_deleted"])
        self.assertEqual(data["item"]["deleted_by"], self.bob.username)
        self.assertEqual(self.client.get(f"/api/murmurs/{post.pk}/comments").status_code, 404)

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

    def test_admin_only_session_can_publish_but_not_directly_delete(self):
        self.client.logout()
        self.become_admin(2)
        self.assertTrue(self.client.get("/api/murmurs/session").json()["can_moderate"])
        self.assertEqual(self.send().status_code, 201)
        other = self.post(author_username=self.bob.username)
        self.assertEqual(self.client.delete(f"/api/murmurs/{other.pk}").status_code, 403)
        self.assertEqual(self.send(f"/api/murmurs/{other.pk}/report", {"reason": "spam"}).status_code, 201)
        report = MurmurReport.objects.get()
        self.assertEqual(self.send(f"/api/admin/murmurs/reports/{report.pk}/review",
                                  {"decision": "resolved", "remove": True}).status_code, 200)
        other.refresh_from_db()
        self.assertTrue(other.is_deleted)
        self.assertEqual(ForumModerationAction.objects.count(), 1)

    def test_session_exposes_profile_cover_for_the_composer(self):
        # 发布卡片用个人主页封面做背景，登录态接口必须带上这张图。
        self.alice.background_url = "/api/forum/images/7"
        self.alice.save(update_fields=["background_url"])
        self.assertEqual(self.client.get("/api/murmurs/session").json()["profile"]["background_url"], "/api/forum/images/7")
        self.alice.background_url = ""
        self.alice.save(update_fields=["background_url"])
        self.assertEqual(self.client.get("/api/murmurs/session").json()["profile"]["background_url"], "")

    def remove_post_via_report(self, post, note="核实违规"):
        self.client.logout()
        self.client.force_login(self.bob)
        self.assertEqual(self.send(f"/api/murmurs/{post.pk}/report", {"reason": "abuse"}).status_code, 201)
        report = MurmurReport.objects.get(murmur=post, reporter_username=self.bob.username)
        self.become_admin(2)
        self.assertEqual(self.send(f"/api/admin/murmurs/reports/{report.pk}/review",
                                  {"decision": "resolved", "remove": True, "note": note}).status_code, 200)
        post.refresh_from_db()

    def login_as(self, user):
        self.client.logout()
        self.client.force_login(user)

    def test_report_removal_starts_appeal_window_and_notifies_both_sides(self):
        post = self.post()
        self.remove_post_via_report(post)
        self.assertTrue(post.is_deleted)
        self.assertTrue(post.deleted_at)
        self.assertEqual(post.deleted_by, "murmur_reviewer")
        self.assertEqual(post.deletion_reason, "核实违规")
        self.assertTrue(post.appeal_deadline)
        author_notice = Notification.objects.get(recipient=self.alice, title__contains="被删除")
        self.assertEqual(author_notice.link, f"/murmurs?appeal=post:{post.pk}")
        reporter_notice = Notification.objects.get(recipient=self.bob, title__contains="举报已处理")
        self.assertTrue(reporter_notice.title.startswith("你提交的举报"))
        self.assertEqual(reporter_notice.link, "")
        self.assertIn("申诉仅对内容作者开放", reporter_notice.body)
        self.assertIn("作者可在", reporter_notice.body)

    def test_pending_count_requires_lv2_and_counts_reports_and_appeals(self):
        post = self.post()
        self.login_as(self.bob)
        self.assertEqual(self.send(f"/api/murmurs/{post.pk}/report", {"reason": "spam"}).status_code, 201)
        self.assertEqual(self.client.get("/api/admin/murmurs/pending-count").status_code, 401)
        self.become_admin(1)
        self.assertEqual(self.client.get("/api/admin/murmurs/pending-count").status_code, 403)
        self.become_admin(2)
        self.assertEqual(self.client.get("/api/admin/murmurs/pending-count").json(),
                         {"reports": 1, "appeals": 0, "total": 1})
        report = MurmurReport.objects.get(murmur=post)
        self.assertEqual(self.send(f"/api/admin/murmurs/reports/{report.pk}/review",
                                  {"decision": "resolved", "remove": True}).status_code, 200)
        self.login_as(self.alice)
        self.assertEqual(self.send("/api/murmurs/appeals",
                                   {"target": f"post:{post.pk}", "reason": "请复核"}).status_code, 201)
        self.become_admin(2)
        self.assertEqual(self.client.get("/api/admin/murmurs/pending-count").json(),
                         {"reports": 0, "appeals": 1, "total": 1})

    def test_remove_review_after_author_self_delete_skips_appeal_notice(self):
        post = self.post()
        self.login_as(self.bob)
        self.assertEqual(self.send(f"/api/murmurs/{post.pk}/report", {"reason": "abuse"}).status_code, 201)
        self.login_as(self.alice)
        self.assertEqual(self.client.delete(f"/api/murmurs/{post.pk}").status_code, 200)
        report = MurmurReport.objects.get(murmur=post)
        self.become_admin(2)
        response = self.send(f"/api/admin/murmurs/reports/{report.pk}/review",
                             {"decision": "resolved", "remove": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["appeal_deadline"], "")
        self.assertFalse(Notification.objects.filter(recipient=self.alice, title__contains="被删除").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.bob, title__contains="举报已处理").exists())

    def test_author_appeal_restores_content_and_notifies(self):
        post = self.post()
        self.remove_post_via_report(post)
        self.login_as(self.alice)
        response = self.send("/api/murmurs/appeals", {"target": f"post:{post.pk}", "reason": "这是正常讨论"})
        self.assertEqual(response.status_code, 201)
        appeal_id = response.json()["appeal"]["id"]
        self.assertTrue(Notification.objects.filter(recipient=self.alice, title="申诉已提交").exists())
        self.become_admin(2)
        review = self.send(f"/api/admin/murmurs/appeals/{appeal_id}/review",
                           {"decision": "accepted", "note": "误判，恢复"})
        self.assertEqual(review.status_code, 200)
        post.refresh_from_db()
        self.assertFalse(post.is_deleted)
        self.assertTrue(post.restored_at)
        self.assertTrue(Notification.objects.filter(recipient=self.alice, title__contains="申诉通过").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.bob, title__contains="复核恢复").exists())
        self.login_as(self.alice)
        self.assertEqual(self.client.get(f"/api/murmurs/{post.pk}").status_code, 200)

    def test_rejected_appeal_keeps_deletion_and_cannot_repeat(self):
        post = self.post()
        self.remove_post_via_report(post)
        self.login_as(self.alice)
        appeal_id = self.send("/api/murmurs/appeals", {"target": f"post:{post.pk}", "reason": "请复核"}).json()["appeal"]["id"]
        self.become_admin(2)
        self.assertEqual(self.send(f"/api/admin/murmurs/appeals/{appeal_id}/review",
                                  {"decision": "rejected", "note": "维持"}).status_code, 200)
        post.refresh_from_db()
        self.assertTrue(post.is_deleted)
        self.assertTrue(Notification.objects.filter(recipient=self.alice, title__contains="申诉未通过").exists())
        self.login_as(self.alice)
        self.assertEqual(self.send("/api/murmurs/appeals", {"target": f"post:{post.pk}", "reason": "再来一次"}).status_code, 409)

    def test_appeal_after_deadline_is_rejected(self):
        post = self.post()
        post.is_deleted = True
        post.deleted_by = "moderator"
        post.deleted_at = timezone.now().isoformat()
        post.appeal_deadline = (timezone.now() - timedelta(days=1)).isoformat()
        post.save()
        response = self.send("/api/murmurs/appeals", {"target": f"post:{post.pk}", "reason": "晚了"})
        self.assertEqual(response.status_code, 400)
        context = self.client.get(f"/api/murmurs/appeals/context?target=post:{post.pk}").json()
        self.assertFalse(context["can_appeal"])
        self.assertEqual(context["message"], "申诉期已结束")

    def test_only_author_can_appeal_and_self_deleted_content_is_excluded(self):
        post = self.post()
        self.remove_post_via_report(post)
        self.login_as(self.bob)
        self.assertEqual(self.send("/api/murmurs/appeals", {"target": f"post:{post.pk}", "reason": "不是我"}).status_code, 403)
        self.login_as(self.alice)
        own = self.post(content="自己删掉")
        self.assertEqual(self.client.delete(f"/api/murmurs/{own.pk}").status_code, 200)
        response = self.send("/api/murmurs/appeals", {"target": f"post:{own.pk}", "reason": "想恢复"})
        self.assertEqual(response.status_code, 400)

    def test_lv1_cannot_review_appeals(self):
        self.become_admin(1)
        self.assertEqual(self.client.get("/api/admin/murmurs/appeals").status_code, 403)

    def test_cannot_report_own_content(self):
        post = self.post()
        self.assertEqual(self.send(f"/api/murmurs/{post.pk}/report", {"reason": "spam"}).status_code, 400)

    def test_comment_removal_and_appeal_restores_comment(self):
        post = self.post()
        comment = MurmurComment.objects.create(murmur=post, author_username=self.bob.username,
                                               content="需要审核", client_key="appeal-comment-key")
        self.assertEqual(self.send(f"/api/murmurs/comments/{comment.pk}/report", {"reason": "abuse"}).status_code, 201)
        report = MurmurReport.objects.get(comment=comment)
        self.become_admin(2)
        self.assertEqual(self.send(f"/api/admin/murmurs/reports/{report.pk}/review",
                                  {"decision": "resolved", "remove": True}).status_code, 200)
        comment.refresh_from_db()
        self.assertTrue(comment.is_deleted)
        self.assertTrue(comment.appeal_deadline)
        self.login_as(self.bob)
        response = self.send("/api/murmurs/appeals", {"target": f"comment:{comment.pk}", "reason": "没有违规"})
        self.assertEqual(response.status_code, 201)
        appeal_id = response.json()["appeal"]["id"]
        self.become_admin(2)
        self.assertEqual(self.send(f"/api/admin/murmurs/appeals/{appeal_id}/review",
                                  {"decision": "accepted"}).status_code, 200)
        comment.refresh_from_db()
        self.assertFalse(comment.is_deleted)
        self.assertTrue(comment.restored_at)
        self.login_as(self.alice)
        self.assertIn(comment.pk, [row["id"] for row in self.client.get(f"/api/murmurs/{post.pk}/comments").json()["items"]])

    def test_comment_report_and_rejection_keep_content(self):
        post = self.post(author_username=self.bob.username)
        comment = MurmurComment.objects.create(murmur=post, author_username=self.bob.username, content="需要审核", client_key="reported-comment")
        self.assertEqual(self.send(f"/api/murmurs/comments/{comment.pk}/report", {"reason": "abuse"}).status_code, 201)
        report = MurmurReport.objects.get()
        self.become_admin(2)
        self.assertEqual(self.send(f"/api/admin/murmurs/reports/{report.pk}/review", {"decision": "rejected", "remove": True}).status_code, 200)
        comment.refresh_from_db()
        self.assertFalse(comment.is_deleted)
        notice = Notification.objects.get(recipient=self.alice, title__contains="举报已驳回")
        self.assertEqual(notice.link, f"/murmurs?post={post.pk}")

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

    def test_video_upload_validation_attach_and_range_playback(self):
        from PIL import Image
        payload = b"\x00\x00\x00\x18ftypmp42" + b"k" * 4096
        poster = BytesIO()
        Image.new("RGB", (64, 36), "red").save(poster, format="PNG")

        def upload(**overrides):
            data = {
                "file": SimpleUploadedFile("clip.mp4", payload, content_type="video/mp4"),
                "duration": "12.5", "width": "1280", "height": "720",
            }
            data.update(overrides)
            return self.client.post("/api/murmurs/videos", data)

        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.assertEqual(Client().post("/api/murmurs/videos", {"duration": "5"}).status_code, 401)
            self.assertEqual(upload(duration="31").status_code, 413)
            self.assertEqual(upload(duration="abc").status_code, 400)
            self.assertEqual(upload(file=SimpleUploadedFile("clip.txt", b"x", content_type="text/plain")).status_code, 400)
            response = upload(poster=SimpleUploadedFile("poster.png", poster.getvalue(), content_type="image/png"))
            self.assertEqual(response.status_code, 201, response.content)
            video = response.json()["video"]
            self.assertEqual(video["duration"], 12.5)
            self.assertTrue(video["poster"].endswith("/poster"))

            self.client.force_login(self.bob)
            self.assertEqual(self.send(data={"content": "借来的视频", "video": video["id"]}).status_code, 400)
            self.client.force_login(self.alice)
            result = self.send(data={"content": "", "video": video["id"]})
            self.assertEqual(result.status_code, 201, result.content)
            item = result.json()["item"]
            self.assertEqual([row["id"] for row in item["videos"]], [video["id"]])
            self.assertEqual(item["videos"][0]["width"], 1280)
            self.assertEqual(MurmurVideo.objects.get(pk=video["id"]).murmur_id, item["id"])
            self.assertEqual(self.send(data={"content": "", "video": video["id"]}).status_code, 400)

            served = self.client.get(video["url"])
            self.assertEqual(served.status_code, 200)
            self.assertEqual(b"".join(served.streaming_content), payload)
            self.assertEqual(served["Accept-Ranges"], "bytes")
            partial = self.client.get(video["url"], HTTP_RANGE="bytes=8-15")
            self.assertEqual(partial.status_code, 206)
            self.assertEqual(partial["Content-Range"], f"bytes 8-15/{len(payload)}")
            self.assertEqual(b"".join(partial.streaming_content), payload[8:16])
            self.assertEqual(self.client.get(video["url"], HTTP_RANGE="bytes=999999-").status_code, 416)
            poster_response = self.client.get(video["poster"])
            self.assertEqual(poster_response.status_code, 200)
            self.assertEqual(poster_response["Content-Type"], "image/webp")

    def test_orphan_videos_are_cleaned_after_a_week(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            stale = MurmurVideo.objects.create(uploader_username=self.alice.username, file="murmurs/videos/stale.mp4", duration=4)
            MurmurVideo.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(days=8))
            response = self.client.post("/api/murmurs/videos", {
                "file": SimpleUploadedFile("clip.webm", b"webm" * 16, content_type="video/webm"),
                "duration": "4",
            })
            self.assertEqual(response.status_code, 201, response.content)
            self.assertFalse(MurmurVideo.objects.filter(pk=stale.pk).exists())
            self.assertEqual(MurmurVideo.objects.filter(uploader_username=self.alice.username).count(), 1)

    def test_video_xaccel_mode_hands_bytes_to_nginx(self):
        """配置了 XACCEL_MEDIA_PREFIX 时，Django 只回一个转发指令，
        不再自己搬运视频字节；Range 也交由 nginx 处理。"""
        from PIL import Image

        payload = b"\x00\x00\x00\x18ftypmp42" + b"k" * 2048
        poster = BytesIO()
        Image.new("RGB", (64, 36), "red").save(poster, format="PNG")
        with TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media, XACCEL_MEDIA_PREFIX="/_protected_uploads"):
                self.client.force_login(self.alice)
                response = self.client.post(
                    "/api/murmurs/videos",
                    {
                        "file": SimpleUploadedFile("clip.mp4", payload, content_type="video/mp4"),
                        "poster": SimpleUploadedFile("poster.png", poster.getvalue(), content_type="image/png"),
                        "duration": "8", "width": "1280", "height": "720",
                    },
                )
                self.assertEqual(response.status_code, 201, response.content)
                video = response.json()["video"]

                served = self.client.get(video["url"], HTTP_RANGE="bytes=0-99")
                self.assertEqual(served.status_code, 200)
                self.assertEqual(served["X-Accel-Redirect"].startswith("/_protected_uploads/murmurs/videos/"), True)
                self.assertEqual(served["Content-Type"], "video/mp4")
                self.assertIn("immutable", served["Cache-Control"])
                self.assertEqual(served.content, b"")

                poster = self.client.get(video["poster"])
                self.assertEqual(poster.status_code, 200)
                self.assertTrue(poster["X-Accel-Redirect"].startswith("/_protected_uploads/murmurs/video-posters/"))
