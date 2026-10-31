# pyright: reportMissingImports=false
"""Tests for the forum API endpoints."""
import io
import json

from django.conf import settings
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import AdminAccount, User
from apps.forum.models import ForumCategory, ForumImage, ForumLike, ForumModerationAction, ForumReply, ForumTopic

def _reset_forum_data():
    ForumLike.objects.all().delete()
    ForumReply.objects.all().delete()
    ForumTopic.objects.all().delete()
    ForumCategory.objects.all().delete()


def _make_category(**kwargs):
    defaults = {"slug": "test", "name": "测试分类", "icon": "测", "color": "#d9232e", "sort_order": 1}
    defaults.update(kwargs)
    return ForumCategory.objects.create(**defaults)


def _make_topic(category, **kwargs):
    defaults = {"title": "测试话题", "content": "话题内容", "author_username": "alice"}
    defaults.update(kwargs)
    return ForumTopic.objects.create(category=category, **defaults)


def _column_is_indexed(table, column):
    """判断某列是否被任意索引/唯一约束覆盖（看列是否是索引的首列）。"""
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    for info in constraints.values():
        if info.get("index") and (info.get("columns") or [None])[0] == column:
            return True
    return False


class ForumCategoryAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()

    def test_categories_returns_list(self):
        resp = self.client.get("/api/forum/categories")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("categories", data)
        self.assertEqual(len(data["categories"]), 1)
        self.assertEqual(data["categories"][0]["slug"], "test")

    def test_categories_include_topic_count(self):
        _make_topic(self.cat)
        resp = self.client.get("/api/forum/categories")
        self.assertEqual(resp.json()["categories"][0]["topic_count"], 1)

    def test_reserved_all_slug_is_hidden(self):
        """数据库中误建的 slug="all" 板块不应出现在侧栏（前端已有"全部话题"入口）。"""
        _make_category(slug="all", name="全部")
        resp = self.client.get("/api/forum/categories")
        slugs = [c["slug"] for c in resp.json()["categories"]]
        self.assertNotIn("all", slugs)
        self.assertEqual(slugs, ["test"])


class ForumTopicListAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.t1 = _make_topic(self.cat, title="Alpha", author_username="alice")
        self.t2 = _make_topic(self.cat, title="Beta", author_username="bob")

    def test_topics_list_returns_all(self):
        resp = self.client.get("/api/forum/topics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 2)

    def test_topics_filter_by_category(self):
        cat2 = _make_category(slug="other", name="其他")
        _make_topic(cat2, title="Other topic")
        resp = self.client.get("/api/forum/topics?category=test")
        data = resp.json()
        self.assertEqual(data["total"], 2)

    def test_topics_search_by_title(self):
        resp = self.client.get("/api/forum/topics?q=Alpha")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["title"], "Alpha")

    def test_topics_search_by_author(self):
        resp = self.client.get("/api/forum/topics?q=bob")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["author"], "bob")

    def test_topics_view_featured(self):
        self.t1.is_featured = True
        self.t1.save()
        resp = self.client.get("/api/forum/topics?view=featured")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertTrue(data["items"][0]["featured"])

    def test_topics_pagination(self):
        # page_size is clamped to the API range 1..50.
        resp = self.client.get("/api/forum/topics?page=1&page_size=1")
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["total"], 2)
        self.assertTrue(data["has_next"])

    def test_ten_per_page_pagination(self):
        """前端按每页 10 条翻页，接口的第 2 页 / 末页边界必须准确。"""
        for i in range(23):
            _make_topic(self.cat, title=f"T{i:02d}")
        first = self.client.get("/api/forum/topics?page=1&page_size=10").json()
        self.assertEqual(first["total"], 25)
        self.assertEqual(len(first["items"]), 10)
        self.assertTrue(first["has_next"])

        last = self.client.get("/api/forum/topics?page=3&page_size=10").json()
        self.assertEqual(len(last["items"]), 5)
        self.assertFalse(last["has_next"])

        # 越界页返回空列表而不是报错，前端据此回退到最后一页
        beyond = self.client.get("/api/forum/topics?page=9&page_size=10").json()
        self.assertEqual(beyond["items"], [])
        self.assertEqual(beyond["total"], 25)

    def test_ten_per_page_does_not_repeat_across_pages(self):
        for i in range(15):
            _make_topic(self.cat, title=f"P{i:02d}")
        seen = []
        for page in (1, 2):
            data = self.client.get(f"/api/forum/topics?page={page}&page_size=10").json()
            seen.extend(item["id"] for item in data["items"])
        self.assertEqual(len(seen), len(set(seen)), "两页之间出现重复话题")

    def test_topics_payload_fields(self):
        resp = self.client.get("/api/forum/topics")
        item = resp.json()["items"][0]
        for field in ("id", "title", "excerpt", "author", "category", "replies", "views", "likes", "liked", "active"):
            self.assertIn(field, item, f"missing field: {field}")

    def test_deleted_topic_excluded(self):
        self.t2.status = ForumTopic.STATUS_DELETED
        self.t2.save()
        resp = self.client.get("/api/forum/topics")
        self.assertEqual(resp.json()["total"], 1)


class ForumTopicDetailAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.topic = _make_topic(self.cat)

    def test_detail_returns_topic(self):
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("topic", data)
        self.assertEqual(data["topic"]["id"], self.topic.pk)

    def test_detail_marks_author_as_allowed_to_manage(self):
        User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        self.client.login(username="alice", password="pass1234")
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertTrue(resp.json()["topic"]["can_manage"])

    def test_detail_increments_views(self):
        self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.client.get(f"/api/forum/topics/{self.topic.pk}")
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertEqual(resp.json()["topic"]["views"], 3)

    def test_detail_includes_replies(self):
        ForumReply.objects.create(topic=self.topic, author_username="bob", content="hi")
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        data = resp.json()
        self.assertEqual(len(data["topic"]["replies_detail"]), 1)
        self.assertEqual(data["topic"]["replies_detail"][0]["author"], "bob")

    def test_detail_paginates_replies_without_counting_extra_views(self):
        ForumReply.objects.bulk_create(
            [ForumReply(topic=self.topic, author_username="bob", content=f"reply {index}") for index in range(31)]
        )
        first = self.client.get(f"/api/forum/topics/{self.topic.pk}?reply_page_size=30")
        self.assertEqual(len(first.json()["topic"]["replies_detail"]), 30)
        self.assertTrue(first.json()["topic"]["reply_has_next"])
        second = self.client.get(f"/api/forum/topics/{self.topic.pk}?reply_page=2&reply_page_size=30")
        self.assertEqual(len(second.json()["topic"]["replies_detail"]), 1)
        self.assertFalse(second.json()["topic"]["reply_has_next"])
        self.topic.refresh_from_db()
        self.assertEqual(self.topic.views, 1)

    def test_detail_404_for_missing(self):
        resp = self.client.get("/api/forum/topics/99999")
        self.assertEqual(resp.status_code, 404)

    def test_detail_404_for_deleted(self):
        self.topic.status = ForumTopic.STATUS_DELETED
        self.topic.save()
        resp = self.client.get(f"/api/forum/topics/{self.topic.pk}")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("已删除", resp.json()["error"])


class ForumCreateTopicAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.user = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")

    def _login(self):
        self.client.login(username="alice", password="pass1234")

    def test_upload_image_accepts_multipart_file(self):
        self._login()
        stream = io.BytesIO()
        Image.new("RGB", (2, 2), color="#ff0000").save(stream, format="PNG")
        response = self.client.post(
            "/api/forum/images",
            {"file": SimpleUploadedFile("inline.png", stream.getvalue(), content_type="image/png")},
        )
        self.assertEqual(response.status_code, 201)
        self.assertRegex(response.json()["image"]["url"], r"^/api/forum/images/\d+$")

    @staticmethod
    def _photo_png(size=(640, 480)):
        """类照片图（平滑渐变 + 噪声）：PNG 压不动而 WebP 收益明显，用来验证重编码。"""
        import math
        import random

        rng = random.Random(20261016)
        image = Image.new("RGB", size)
        pixels = image.load()
        for y in range(size[1]):
            for x in range(size[0]):
                noise = rng.randint(-18, 18)
                clamp = lambda v: max(0, min(255, int(v) + noise))
                pixels[x, y] = (
                    clamp(120 + 100 * math.sin(x / 40)),
                    clamp(120 + 100 * math.sin(y / 35)),
                    clamp(120 + 80 * math.cos((x + y) / 50)),
                )
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return stream.getvalue()

    def test_upload_image_reencodes_to_webp_and_shrinks(self):
        self._login()
        raw = self._photo_png()
        response = self.client.post(
            "/api/forum/images",
            {"file": SimpleUploadedFile("photo.png", raw, content_type="image/png")},
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()["image"]
        self.assertEqual((payload["width"], payload["height"]), (640, 480))
        row = ForumImage.objects.get(pk=payload["id"])
        self.assertEqual(row.content_type, "image/webp")
        self.assertLess(row.file_size, len(raw), "WebP 重编码应当减小体积")

    def test_upload_image_returns_dimensions_for_existing_rows(self):
        """列表与详情里的图片要带宽高，前端才能写 width/height 防 CLS。"""
        self._login()
        stream = io.BytesIO()
        Image.new("RGB", (320, 240), color="#123456").save(stream, format="PNG")
        response = self.client.post(
            "/api/forum/images",
            {"file": SimpleUploadedFile("a.png", stream.getvalue(), content_type="image/png")},
        )
        image_id = response.json()["image"]["id"]
        row = ForumImage.objects.get(pk=image_id)
        self.assertEqual((row.width, row.height), (320, 240))

    def test_upload_image_downscales_oversized(self):
        self._login()
        stream = io.BytesIO()
        Image.new("RGB", (3200, 2400), color="#224466").save(stream, format="PNG")
        raw = stream.getvalue()
        response = self.client.post(
            "/api/forum/images",
            {"file": SimpleUploadedFile("big.png", raw, content_type="image/png")},
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()["image"]
        self.assertEqual(max(payload["width"], payload["height"]), 1600)

    def test_served_image_is_immutable_and_cached(self):
        self._login()
        stream = io.BytesIO()
        Image.new("RGB", (8, 8), color="#00ff00").save(stream, format="PNG")
        created = self.client.post(
            "/api/forum/images",
            {"file": SimpleUploadedFile("c.png", stream.getvalue(), content_type="image/png")},
        ).json()["image"]

        response = self.client.get(created["url"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("immutable", response["Cache-Control"])
        self.assertIn("max-age=31536000", response["Cache-Control"])
        self.assertTrue(response["ETag"])

    def test_create_requires_login(self):
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "t", "content": "c", "category": "test"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_topic_success(self):
        self._login()
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "新话题标题", "content": "详细内容描述", "category": "test", "tags": "Django, 测试"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["topic"]["title"], "新话题标题")
        self.assertEqual(data["topic"]["author"], "alice")
        self.assertIn("Django", data["topic"]["tags"])

    def test_create_validates_empty_title(self):
        self._login()
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "", "content": "c", "category": "test"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_validates_missing_category(self):
        self._login()
        resp = self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "t", "content": "c", "category": "nonexistent"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_persists_in_db(self):
        self._login()
        self.client.post(
            "/api/forum/topics/create",
            json.dumps({"title": "持久化测试", "content": "content", "category": "test"}),
            content_type="application/json",
        )
        self.assertTrue(ForumTopic.objects.filter(title="持久化测试").exists())


class ForumReplyAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.topic = _make_topic(self.cat)
        self.user = User.objects.create_user(username="bob", password="pass1234", email="b@example.com")
        self.client.login(username="bob", password="pass1234")

    def test_reply_success(self):
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "这是一条回复"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["reply"]["author"], "bob")
        self.assertEqual(data["reply"]["content"], "这是一条回复")

    def test_reply_persists(self):
        self.client.post(
            f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "DB reply"}),
            content_type="application/json",
        )
        self.assertEqual(self.topic.replies.count(), 1)

    def test_reply_404_for_closed_topic(self):
        self.topic.status = ForumTopic.STATUS_CLOSED
        self.topic.save()
        resp = self.client.post(
            f"/api/forum/topics/{self.topic.pk}/replies",
            json.dumps({"content": "reply"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)


class ForumLikeAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        self.topic = _make_topic(self.cat)
        self.user = User.objects.create_user(username="carol", password="pass1234", email="c@example.com")
        self.client.login(username="carol", password="pass1234")

    def test_like_topic(self):
        resp = self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["likes"], 1)
        self.assertTrue(data["liked"])

    def test_unlike_topic(self):
        self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        resp = self.client.delete(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["likes"], 0)
        self.assertFalse(resp.json()["liked"])

    def test_like_idempotent(self):
        self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(ForumLike.objects.filter(topic=self.topic).count(), 1)

    def test_like_requires_login(self):
        self.client.logout()
        resp = self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 401)

    def test_like_query_budget(self):
        """点赞会同时给点赞者和作者做统计 + 判勋章，查询数必须有上限。

        改造前每次点赞 56 条 SQL（两次完整 compute_user_stats + 两次勋章判定），
        现在两人共用一轮批量统计，实测 36 条；预算留 4 条余量，防止回退。
        """
        _make_topic(self.cat, title="预热", content="c")  # 让统计不是空集
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(ctx.captured_queries), 40, f"点赞 SQL 数 {len(ctx.captured_queries)} 超预算")

    def test_unlike_query_budget(self):
        self.client.post(f"/api/forum/topics/{self.topic.pk}/like")
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.delete(f"/api/forum/topics/{self.topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(ctx.captured_queries), 40, f"取消点赞 SQL 数 {len(ctx.captured_queries)} 超预算")

    def test_like_still_awards_points_and_notifies_author(self):
        """批量化不能改变业务结果：作者仍要收到积分和通知。"""
        author = User.objects.create_user(username="author", password="pass1234", email="au@example.com")
        topic = _make_topic(self.cat, title="被赞的帖", author_username="author")
        resp = self.client.post(f"/api/forum/topics/{topic.pk}/like")
        self.assertEqual(resp.status_code, 200)
        from apps.notifications.models import Notification

        self.assertTrue(
            Notification.objects.filter(recipient=author, type="like").exists(),
            "作者没有收到点赞通知，批量化改坏了通知链路",
        )


class ForumIndexTests(TestCase):
    """列表/统计/勋章都按 username 过滤，这些字段必须有索引。"""

    EXPECTED_INDEXES = [
        ("forum_topics", "author_username"),
        ("forum_replies", "author_username"),
        ("forum_likes", "username"),
        ("forum_reply_likes", "username"),
        ("forum_topic_boosts", "username"),
        ("forum_images", "uploader_username"),
        ("external_project_votes", "username"),
    ]

    def test_username_columns_are_indexed(self):
        for table, column in self.EXPECTED_INDEXES:
            with self.subTest(table=table, column=column):
                self.assertTrue(
                    _column_is_indexed(table, column),
                    f"{table}.{column} 缺少索引（列表/统计按它过滤会全表扫描）",
                )


class ForumStatsAPITests(TestCase):
    def setUp(self):
        _reset_forum_data()
        self.cat = _make_category()
        _make_topic(self.cat)
        _make_topic(self.cat, title="Topic 2")
        User.objects.create_user(username="u1", password="p", email="u1@x.com")
        User.objects.create_user(username="u2", password="p", email="u2@x.com")

    def test_stats_returns_counts(self):
        resp = self.client.get("/api/forum/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["topics"], 2)
        self.assertGreaterEqual(data["members"], 2)
        self.assertIn("replies", data)


class ForumObjectAuthorizationTests(TestCase):
    """Exercise the real mutation endpoints with independent user sessions."""

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username="authz-author")
        cls.other = User.objects.create_user(username="authz-other")
        cls.moderator = User.objects.create_user(username="authz-moderator")
        cls.limited_admin = User.objects.create_user(username="authz-admin-lv1")
        cls.admin = User.objects.create_user(username="authz-admin-lv2")
        cls.super_admin = User.objects.create_user(username="authz-super")
        for user, level, is_super in [
            (cls.limited_admin, 1, 0), (cls.admin, 2, 0), (cls.super_admin, 3, 1),
        ]:
            AdminAccount.objects.create(
                username=user.username, admin_level=level, is_super=is_super,
                password_hash=user.password, created_at="2026-10-18T00:00:00Z",
            )
        cls.category = _make_category(slug="authorization-inside")
        cls.outside_category = _make_category(slug="authorization-outside")
        cls.category.moderators.add(cls.moderator)
        cls.topic = _make_topic(cls.category, author_username=cls.author.username)
        cls.outside_topic = _make_topic(cls.outside_category, author_username=cls.author.username)
        cls.reply = ForumReply.objects.create(topic=cls.topic, author_username=cls.author.username, content="原始回复")
        cls.outside_reply = ForumReply.objects.create(topic=cls.outside_topic, author_username=cls.author.username, content="板块外回复")

    def _client(self, user=None, *, csrf=False):
        client = Client(enforce_csrf_checks=csrf)
        if user is not None:
            client.force_login(user)
        return client

    def _objects(self):
        return [self.topic, self.reply, self.outside_topic, self.outside_reply]

    def _path(self, obj):
        kind = "topics" if isinstance(obj, ForumTopic) else "replies"
        return f"/api/forum/{kind}/{obj.pk}/manage"

    def _request(self, client, obj, method, *, spoof=False, **headers):
        body = {"title": "修改后的标题", "content": "修改后的内容", "tags": "test"}
        if spoof:
            body.update(author_username=self.author.username, username=self.author.username, role="admin", admin_level=3, is_super=True)
            headers.update(HTTP_X_USERNAME=self.author.username, HTTP_X_ROLE="admin", HTTP_X_ADMIN_LEVEL="3")
        return getattr(client, method)(self._path(obj), data=json.dumps(body), content_type="application/json", **headers)

    def _assert_denied(self, client, objects, status, *, spoof=False, **headers):
        action_count = ForumModerationAction.objects.count()
        for obj in objects:
            before = type(obj).objects.values().get(pk=obj.pk)
            for method in ["patch", "put", "delete"]:
                with self.subTest(model=type(obj).__name__, pk=obj.pk, method=method):
                    response = self._request(client, obj, method, spoof=spoof, **headers)
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(type(obj).objects.values().get(pk=obj.pk), before)
        self.assertEqual(ForumModerationAction.objects.count(), action_count)

    def _assert_allowed(self, client, objects):
        for obj in objects:
            original_author = obj.author_username
            for method in ["patch", "put"]:
                with self.subTest(model=type(obj).__name__, method=method):
                    self.assertEqual(self._request(client, obj, method).status_code, 200)
                    obj.refresh_from_db()
                    self.assertEqual(obj.content, "修改后的内容")
                    self.assertEqual(obj.author_username, original_author)
            self.assertEqual(self._request(client, obj, "delete").status_code, 200)
            obj.refresh_from_db()
            if isinstance(obj, ForumTopic):
                self.assertEqual(obj.status, ForumTopic.STATUS_DELETED)
            else:
                self.assertTrue(obj.is_deleted)

    def test_guest_cannot_edit_or_delete_topics_or_replies(self):
        self._assert_denied(self._client(), self._objects(), 401)

    def test_other_user_cannot_edit_or_delete_topics_or_replies(self):
        self._assert_denied(self._client(self.other), self._objects(), 403)

    def test_request_body_headers_and_cookies_cannot_spoof_author_or_admin(self):
        client = self._client(self.other)
        client.cookies[settings.ADMIN_SESSION_COOKIE] = "forged-admin-token"
        client.cookies["admin_username"] = self.author.username
        client.cookies["admin_is_super"] = "true"
        self._assert_denied(client, self._objects(), 403, spoof=True)

    def test_invalid_session_cannot_impersonate_author(self):
        client = self._client()
        client.cookies[settings.SESSION_COOKIE_NAME] = "invalid-session-token"
        client.cookies[settings.ADMIN_SESSION_COOKIE] = "invalid-admin-token"
        self._assert_denied(client, self._objects(), 401, spoof=True)

    def test_author_can_edit_and_delete_own_content_in_any_category(self):
        # Delete replies before their parent topic is hidden.
        self._assert_allowed(self._client(self.author), [self.reply, self.topic, self.outside_reply, self.outside_topic])

    def test_topic_author_cannot_manage_another_users_reply(self):
        reply = ForumReply.objects.create(topic=self.topic, author_username=self.other.username, content="其他人的回复")
        self._assert_denied(self._client(self.author), [reply], 403)

    def test_moderator_is_limited_to_assigned_category(self):
        client = self._client(self.moderator)
        self._assert_denied(client, [self.outside_topic, self.outside_reply], 403)
        self._assert_allowed(client, [self.reply, self.topic])

    def test_level_one_admin_is_limited_to_own_content(self):
        client = self._client(self.limited_admin)
        self._assert_denied(client, self._objects(), 403)
        topic = _make_topic(self.category, author_username=self.limited_admin.username)
        reply = ForumReply.objects.create(topic=topic, author_username=self.limited_admin.username, content="管理员自己的回复")
        self._assert_allowed(client, [reply, topic])

    def test_level_two_admin_can_manage_content_across_categories(self):
        self._assert_allowed(self._client(self.admin), [self.reply, self.topic, self.outside_reply, self.outside_topic])

    def test_super_admin_can_manage_content_across_categories(self):
        self._assert_allowed(self._client(self.super_admin), [self.reply, self.topic, self.outside_reply, self.outside_topic])

    def test_detail_permission_flag_matches_viewer_and_category(self):
        for user, inside, outside in [
            (None, False, False), (self.author, True, True), (self.other, False, False),
            (self.moderator, True, False), (self.limited_admin, False, False),
            (self.admin, True, True), (self.super_admin, True, True),
        ]:
            client = self._client(user)
            for topic, allowed in [(self.topic, inside), (self.outside_topic, outside)]:
                with self.subTest(user=getattr(user, "username", "guest"), topic=topic.pk):
                    response = client.get(f"/api/forum/topics/{topic.pk}")
                    self.assertEqual(response.status_code, 200)
                    self.assertIs(response.json()["topic"]["can_manage"], allowed)

    def test_csrf_protection_and_valid_token_do_not_bypass_ownership(self):
        author = self._client(self.author, csrf=True)
        response = author.get("/forum")
        response.close()
        token = author.cookies[settings.CSRF_COOKIE_NAME].value
        self._assert_denied(author, self._objects(), 403)
        self._assert_denied(author, self._objects(), 403, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://untrusted.example")
        self.assertEqual(self._request(author, self.topic, "patch", HTTP_X_CSRFTOKEN=token).status_code, 200)
        other = self._client(self.other, csrf=True)
        response = other.get("/forum")
        response.close()
        token = other.cookies[settings.CSRF_COOKIE_NAME].value
        self._assert_denied(other, self._objects(), 403, HTTP_X_CSRFTOKEN=token)

    def test_users_and_non_super_admins_cannot_appoint_themselves_moderator(self):
        for user, status in [(self.other, 401), (self.limited_admin, 403), (self.admin, 403)]:
            client = self._client(user)
            response = client.patch(
                f"/api/forum/categories/{self.category.pk}/moderators",
                data=json.dumps({"moderators": [user.username]}), content_type="application/json",
            )
            self.assertEqual(response.status_code, status)
            self.assertEqual(list(self.category.moderators.values_list("username", flat=True)), [self.moderator.username])
