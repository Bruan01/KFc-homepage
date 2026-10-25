# pyright: reportMissingImports=false
"""Feeds tests: RSS/Atom parsing, AIHOT mapping, API shape, failure isolation."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User

from .models import FeedFetchRun, FeedItem, FeedSource
from .services import AIHOT_CATEGORY_MAP, parse_feed
from .sources import SOURCES

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Sample</title>
<item>
  <title>OpenAI releases &amp;new model</title>
  <link>https://example.com/post-1</link>
  <guid>post-1</guid>
  <pubDate>Thu, 23 Oct 2026 08:00:00 GMT</pubDate>
  <description><![CDATA[<p>A <b>bold</b> summary with tags.</p>]]></description>
</item>
<item>
  <title>No link item</title>
  <description>should be skipped</description>
</item>
</channel></rss>
"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Sample</title>
<entry>
  <title>Atom entry title</title>
  <link rel="alternate" href="https://example.com/atom-1"/>
  <id>tag:example.com,2026:atom-1</id>
  <published>2026-10-22T10:30:00Z</published>
  <summary>Plain atom summary</summary>
</entry>
</feed>
"""

AIHOT_SAMPLE = {
    "schemaVersion": 1,
    "items": [
        {
            "id": "gwhdq3jo5p1z27wh2i46ntd2s",
            "title": "Kimi 发布开源旗舰模型 K3.1 Pro",
            "summary": "月之暗面发布旗舰模型，参数 2.8T。",
            "source": {"name": "公众号：数字生命卡兹克"},
            "links": {
                "aihot": "https://aihot.news/items/gwhdq3jo5p1z27wh2i46ntd2s",
                "original": "https://mp.weixin.qq.com/s/example",
            },
            "publishedAt": "2026-10-24T02:08:43.000Z",
            "category": "ai-models",
            "score": 78,
            "attribution": {"name": "AIHOT", "url": "https://aihot.news/items/gwhdq3jo5p1z27wh2i46ntd2s"},
        }
    ],
}


class ParseFeedTests(TestCase):
    def test_rss_parsing_strips_html_and_skips_linkless(self):
        entries = parse_feed(RSS_SAMPLE)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["title"], "OpenAI releases &new model")
        self.assertEqual(entry["url"], "https://example.com/post-1")
        self.assertEqual(entry["guid"], "post-1")
        self.assertNotIn("<", entry["summary"])
        self.assertIn("bold summary", entry["summary"])
        self.assertIsNotNone(entry["published_at"])

    def test_atom_parsing_uses_alternate_link(self):
        entries = parse_feed(ATOM_SAMPLE)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["url"], "https://example.com/atom-1")
        self.assertEqual(entries[0]["guid"], "tag:example.com,2026:atom-1")
        self.assertIsNotNone(entries[0]["published_at"])


class FeedsApiTests(TestCase):
    def setUp(self):
        self.source = FeedSource.objects.create(
            name="AIHOT", slug="aihot", category="aggregator",
            site_url="https://aihot.news/", fetch_kind="api_aihot",
            feed_url="https://aihot.news/api/v1/items?mode=selected&limit=100",
        )

    def _add_item(self, guid, category="model", score=80, hours_ago=1):
        return FeedItem.objects.create(
            source=self.source, title=f"Item {guid}", url=f"https://example.com/{guid}",
            guid=guid, summary="s", language="zh", category=category, score=score,
            upstream_name="X：OpenAI (@OpenAI)", via_name="AIHOT", via_url="https://aihot.news/x",
            published_at=timezone.now() - timedelta(hours=hours_ago),
        )

    def test_sources_directory_shape(self):
        self._add_item("a")
        response = self.client.get("/api/feeds/sources")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["items"])
        entry = payload["items"][0]
        for key in ("slug", "name", "category", "site_url", "has_feed"):
            self.assertIn(key, entry)

    def test_items_timeline_shape_and_filters(self):
        self._add_item("a", category="paper", hours_ago=2)
        self._add_item("b", category="model", hours_ago=1)
        response = self.client.get("/api/feeds/items", {"category": "model"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        item = payload["items"][0]
        self.assertEqual(item["title"], "Item b")
        self.assertEqual(item["category_label"], "模型")
        self.assertEqual(item["score"], 80)
        self.assertEqual(item["upstream_name"], "X：OpenAI (@OpenAI)")
        self.assertEqual(item["via_name"], "AIHOT")
        codes = [c["code"] for c in payload["categories"]]
        self.assertIn("model", codes)
        # 未知分类返回空列表而不是报错
        empty = self.client.get("/api/feeds/items", {"category": "nope"}).json()
        self.assertEqual(empty["total"], 0)

    def test_items_reject_invalid_limit(self):
        response = self.client.get("/api/feeds/items", {"limit": "abc"})
        self.assertEqual(response.status_code, 200)

    def test_hot_endpoint_proxies_aihot(self):
        from . import views as feed_views
        fake_topics = [{"rank": 1, "title": "T", "source": "S",
                        "url": "https://example.com",
                        "signal_count": 5, "source_count": 2}]
        feed_views._hot_cache.clear()
        with mock.patch("apps.feeds.services.fetch_aihot_hot_topics", return_value=fake_topics):
            payload = self.client.get("/api/feeds/hot").json()
        self.assertEqual(payload["items"][0]["title"], "T")
        self.assertEqual(payload["items"][0]["signal_count"], 5)
        self.assertEqual(payload["via"]["name"], "AIHOT")


class FetchIsolationTests(TestCase):
    def test_run_fetch_isolates_failures(self):
        ok_source = FeedSource.objects.create(
            name="OK", slug="ok", category="media",
            site_url="https://ok.example", feed_url="https://ok.example/rss",
        )
        bad_source = FeedSource.objects.create(
            name="Bad", slug="bad", category="media",
            site_url="https://bad.example", feed_url="https://bad.example/rss",
        )

        from . import services as feed_services

        with mock.patch.object(feed_services, "_http_get") as fake_get:
            def side_effect(url):
                if "bad.example" in url:
                    raise feed_services.URLError("boom")
                return RSS_SAMPLE.encode("utf-8")
            fake_get.side_effect = side_effect
            results = feed_services.run_fetch()

        self.assertEqual(results["ok"]["status"], "success")
        self.assertEqual(results["ok"]["count"], 1)
        self.assertEqual(results["bad"]["status"], "failed")
        self.assertEqual(FeedItem.objects.filter(source=ok_source).count(), 1)
        self.assertTrue(FeedFetchRun.objects.filter(source_slug="bad", status="failed").exists())
        ok_source.refresh_from_db()
        self.assertIsNotNone(ok_source.last_fetched_at)
        bad_source.refresh_from_db()
        self.assertIsNone(bad_source.last_fetched_at)

    def test_fetch_source_dedupes_by_guid(self):
        from . import services as feed_services
        source = FeedSource.objects.create(
            name="Dedupe", slug="dedupe", category="media",
            site_url="https://example.com", feed_url="https://example.com/rss",
        )
        run = FeedFetchRun.objects.create(source_slug=source.slug)
        with mock.patch.object(feed_services, "_http_get", return_value=RSS_SAMPLE.encode("utf-8")):
            first = feed_services.fetch_source(source, run)
            second = feed_services.fetch_source(source, run)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(FeedItem.objects.filter(source=source).count(), 1)

    def test_aihot_mapping_and_upsert(self):
        source = FeedSource.objects.create(
            name="AIHOT", slug="aihot-2", category="aggregator",
            site_url="https://aihot.news/", fetch_kind="api_aihot",
        )
        raw = __import__("json").dumps(AIHOT_SAMPLE).encode("utf-8")

        class FakeResponse:
            status = 200
            headers = {"ETag": 'W/"abc"'}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return raw

        from . import services as feed_services
        feed_services._aihot_etags.clear()
        with mock.patch.object(feed_services, "_open_with_tls_fallback", return_value=FakeResponse()):
            first = feed_services.fetch_aihot_items(source)
            # 同一条再次抓取：upsert 更新而非重复
            with mock.patch.object(feed_services, "_open_with_tls_fallback", return_value=FakeResponse()):
                second = feed_services.fetch_aihot_items(source)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        item = FeedItem.objects.get(source=source, guid="gwhdq3jo5p1z27wh2i46ntd2s")
        self.assertEqual(item.category, "model")
        self.assertEqual(item.score, 78)
        self.assertEqual(item.upstream_name, "公众号：数字生命卡兹克")
        self.assertEqual(item.via_name, "AIHOT")
        self.assertTrue(item.url.startswith("https://mp.weixin.qq.com/"))
        # 精选标记由第二个 mode=selected 请求补齐（样例数据本身没有 selected 字段）
        self.assertTrue(item.is_selected)
        # 词表映射完整
        self.assertEqual(len(AIHOT_CATEGORY_MAP), 6)

    def test_aihot_dual_stream_marks_selected(self):
        """mode=all 拉时间流、mode=selected 补精选标记；仅在精选流里的旧条目也要入库。"""
        import json as json_mod

        source = FeedSource.objects.create(
            name="AIHOT", slug="aihot-3", category="aggregator",
            site_url="https://aihot.news/", fetch_kind="api_aihot",
            feed_url="https://aihot.news/api/v1/items?mode=all&limit=100",
        )
        all_payload = json_mod.dumps({"items": [
            {"id": "fresh-1", "title": "今日新条目", "summary": "s",
             "source": {"name": "X：a"}, "links": {"original": "https://example.com/f1"},
             "publishedAt": "2026-10-25T10:00:00.000Z", "category": "ai-models",
             "score": 30, "selected": False},
        ]}).encode("utf-8")
        selected_payload = json_mod.dumps({"items": [
            {"id": "fresh-1", "title": "今日新条目（精选）", "summary": "s",
             "source": {"name": "X：a"}, "links": {"original": "https://example.com/f1"},
             "publishedAt": "2026-10-25T10:00:00.000Z", "category": "ai-models",
             "score": 30, "selected": True},
            {"id": "curated-old-1", "title": "精选流里的旧条目", "summary": "s",
             "source": {"name": "X：b"}, "links": {"original": "https://example.com/c1"},
             "publishedAt": "2026-10-19T08:00:00.000Z", "category": "paper",
             "score": 88, "selected": True},
        ]}).encode("utf-8")

        class FakeResponse:
            status = 200
            headers = {}

            def __init__(self, body):
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return self._body

        from . import services as feed_services
        feed_services._aihot_etags.clear()

        def fake_open(request, timeout):
            if "mode=selected" in request.full_url:
                return FakeResponse(selected_payload)
            return FakeResponse(all_payload)

        with mock.patch.object(feed_services, "_open_with_tls_fallback", side_effect=fake_open):
            created = feed_services.fetch_aihot_items(source)
        # all 流新建 1 条；selected 流再补 1 条旧精选
        self.assertEqual(created, 2)
        fresh = FeedItem.objects.get(source=source, guid="fresh-1")
        old = FeedItem.objects.get(source=source, guid="curated-old-1")
        self.assertTrue(fresh.is_selected)
        self.assertTrue(old.is_selected)
        self.assertEqual(fresh.title, "今日新条目（精选）")

    def test_sources_seed_data_shape(self):
        slugs = [s["slug"] for s in SOURCES]
        self.assertEqual(len(slugs), len(set(slugs)))
        fetchers = [s for s in SOURCES if s.get("feed_url")]
        self.assertEqual(len(fetchers), 1)
        self.assertEqual(fetchers[0]["slug"], "aihot")
        self.assertEqual(fetchers[0].get("fetch_kind"), "api_aihot")


class AskXiaokTests(TestCase):
    def setUp(self):
        self.source = FeedSource.objects.create(
            name="AIHOT", slug="aihot", category="aggregator",
            site_url="https://aihot.news/", fetch_kind="api_aihot",
        )
        self.user = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        FeedItem.objects.create(
            source=self.source, title="Kimi 发布 K3.1 Pro", url="https://example.com/kimi",
            guid="kimi", summary="2.8T 参数", language="zh", category="model", score=88,
            published_at=timezone.now() - timedelta(hours=2),
        )
        from apps.community_ai.models import AssistantSettings
        AssistantSettings.objects.create(enabled=True, base_url="https://api.example.com/v1", model="test-model")
        from . import views as feed_views
        feed_views._ask_counters.clear()

    def test_ask_requires_login(self):
        response = self.client.post("/api/feeds/ask", data='{"question":"今天有什么大事"}', content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_ask_returns_answer_with_refs(self):
        self.client.login(username="alice", password="pass1234")
        with mock.patch("apps.community_ai.provider.complete", return_value="今天最值得关注 Kimi 新模型【1】") as fake:
            response = self.client.post("/api/feeds/ask", data='{"question":"今天有什么大事"}', content_type="application/json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("K3.1", payload["answer"] + str(payload["refs"]))
        self.assertEqual(payload["refs"][0]["n"], 1)
        self.assertEqual(payload["refs"][0]["url"], "https://example.com/kimi")
        fake.assert_called_once()

    def test_ask_rate_limit(self):
        self.client.login(username="alice", password="pass1234")
        with mock.patch("apps.community_ai.provider.complete", return_value="好"):
            codes = []
            for _ in range(12):
                response = self.client.post("/api/feeds/ask", data='{"question":"再讲讲"}', content_type="application/json")
                codes.append(response.status_code)
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(codes[10], 429)


class DailyPushTests(TestCase):
    def setUp(self):
        self.source = FeedSource.objects.create(
            name="AIHOT", slug="aihot", category="aggregator",
            site_url="https://aihot.news/", fetch_kind="api_aihot",
        )
        FeedItem.objects.create(
            source=self.source, title="头条", url="https://example.com/1",
            guid="a1", summary="", language="zh", category="model", score=90,
            published_at=timezone.now() - timedelta(hours=1),
        )
        self.alice = User.objects.create_user(username="alice", password="pass1234", email="a@example.com")
        User.objects.create_user(username="community_guest_20261024", password="x", email="g@example.com")

    def test_daily_push_idempotent(self):
        from django.core.management import call_command
        from apps.notifications.models import Notification
        call_command("push_feed_daily")
        count = Notification.objects.filter(type="feed", recipient=self.alice).count()
        self.assertEqual(count, 1)
        self.assertFalse(Notification.objects.filter(recipient__username="community_guest_20261024").exists())
        call_command("push_feed_daily")  # 当天重复执行不再推
        self.assertEqual(Notification.objects.filter(type="feed", recipient=self.alice).count(), 1)


class WeeklyDigestTests(TestCase):
    def setUp(self):
        self.source = FeedSource.objects.create(
            name="AIHOT", slug="aihot", category="aggregator",
            site_url="https://aihot.news/", fetch_kind="api_aihot",
        )
        FeedItem.objects.create(
            source=self.source, title="周内大事", url="https://example.com/w1",
            guid="w1", summary="", language="zh", category="model", score=92,
            published_at=timezone.now() - timedelta(days=2),
        )
        self.xiaok = User.objects.create_user(username="xiaok", password="pass1234", email="x@example.com")
        from apps.accounts.models import OfficialCommunitySettings
        OfficialCommunitySettings.objects.create(account=self.xiaok)
        from apps.forum.models import ForumCategory
        ForumCategory.objects.get_or_create(slug="product", defaults={"name": "产品", "sort_order": 1})

    def test_weekly_publish_idempotent(self):
        from django.core.management import call_command
        from apps.forum.models import ForumTopic
        call_command("publish_feed_weekly")
        topic = ForumTopic.objects.filter(author_username="xiaok", title__startswith="AI 电讯周报").first()
        self.assertIsNotNone(topic)
        self.assertIn("周内大事", topic.content)
        call_command("publish_feed_weekly")  # 本周重复执行不再发
        self.assertEqual(ForumTopic.objects.filter(author_username="xiaok", title__startswith="AI 电讯周报").count(), 1)
