# pyright: reportMissingImports=false
"""Feeds tests: RSS/Atom parsing, AIHOT mapping, API shape, failure isolation."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

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
        # 词表映射完整
        self.assertEqual(len(AIHOT_CATEGORY_MAP), 6)

    def test_sources_seed_data_shape(self):
        slugs = [s["slug"] for s in SOURCES]
        self.assertEqual(len(slugs), len(set(slugs)))
        fetchers = [s for s in SOURCES if s.get("feed_url")]
        self.assertEqual(len(fetchers), 1)
        self.assertEqual(fetchers[0]["slug"], "aihot")
        self.assertEqual(fetchers[0].get("fetch_kind"), "api_aihot")
