# pyright: reportMissingImports=false
"""Visit stats: filtering rules, UV dedupe, grouping, admin API, retention."""
from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.stats import services, taxonomy
from apps.stats.models import VisitDaily, VisitPageDaily, VisitReferrerDaily, VisitVisitor

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


class VisitStatsBase(TestCase):
    def setUp(self):
        services.reset()
        for model in (VisitPageDaily, VisitReferrerDaily, VisitVisitor, VisitDaily):
            model.objects.all().delete()

    def tearDown(self):
        services.reset()

    def visit(self, path="/", *, ip="203.0.113.8", ua=BROWSER_UA, referer=""):
        extra = {"REMOTE_ADDR": ip, "HTTP_USER_AGENT": ua}
        if referer:
            extra["HTTP_REFERER"] = referer
        response = self.client.get(path, **extra)
        services.flush()
        return response


class VisitCountingTests(VisitStatsBase):
    def test_counts_home_page_and_attributes_direct_traffic(self):
        response = self.visit("/")
        self.assertEqual(response.status_code, 200)
        today = timezone.localdate().isoformat()
        row = VisitDaily.objects.get(date=today)
        self.assertEqual((row.pv, row.uv), (1, 1))
        self.assertEqual(VisitPageDaily.objects.get(date=today, page_key="home").pv, 1)
        self.assertEqual(VisitReferrerDaily.objects.get(date=today, source_key="direct").pv, 1)

    def test_repeat_visitor_counts_pv_but_not_uv(self):
        self.visit("/")
        self.visit("/forum")
        self.visit("/forum", ua="Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Safari/605.1.15")
        today = timezone.localdate().isoformat()
        row = VisitDaily.objects.get(date=today)
        self.assertEqual(row.pv, 3)
        self.assertEqual(row.uv, 2)
        self.assertEqual(VisitPageDaily.objects.get(date=today, page_key="forum").pv, 2)

    def test_flush_is_idempotent(self):
        self.visit("/")
        services.flush()
        services.flush()
        self.assertEqual(VisitDaily.objects.get(date=timezone.localdate().isoformat()).pv, 1)

    def test_skips_bots_and_privacy_signals(self):
        self.visit("/", ua="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
        self.client.get("/", REMOTE_ADDR="203.0.113.9", HTTP_USER_AGENT=BROWSER_UA, HTTP_DNT="1")
        services.flush()
        self.assertFalse(VisitDaily.objects.exists())

    def test_skips_api_admin_and_static_requests(self):
        self.visit("/api/announcements/current")
        self.visit("/admin")
        self.visit("/static/styles.css")
        self.assertFalse(VisitDaily.objects.exists())

    def test_ignores_non_get_requests(self):
        self.client.post("/api/announcements/current")
        services.flush()
        self.assertFalse(VisitDaily.objects.exists())


class SourceAttributionTests(VisitStatsBase):
    def test_classifies_known_platforms(self):
        self.visit("/", referer="https://mp.weixin.qq.com/s/abc")
        self.visit("/", referer="https://www.baidu.com/s?wd=kflow")
        self.visit("/", referer="https://www.google.com.hk/search?q=kflow")
        today = timezone.localdate().isoformat()
        keys = set(VisitReferrerDaily.objects.filter(date=today).values_list("source_key", flat=True))
        self.assertEqual(keys, {"wechat", "baidu", "google"})

    def test_same_site_referrer_is_internal(self):
        self.visit("/forum", referer="http://testserver/")
        today = timezone.localdate().isoformat()
        self.assertEqual(VisitReferrerDaily.objects.get(date=today).source_key, "internal")

    def test_unknown_referrer_keeps_hostname(self):
        self.visit("/", referer="https://www.example.com/post/1")
        today = timezone.localdate().isoformat()
        self.assertEqual(VisitReferrerDaily.objects.get(date=today).source_key, "example.com")

    def test_taxonomy_groups_dynamic_routes(self):
        self.assertEqual(taxonomy.classify_page("/product/kflow-pro"), "product_detail")
        self.assertEqual(taxonomy.classify_page("/forum/user/alice/"), "forum_profile")
        self.assertEqual(taxonomy.classify_page("/tutorials/hello"), "tutorial_detail")
        self.assertEqual(taxonomy.classify_page("/unknown-route"), "other")
        self.assertEqual(taxonomy.page_label("product_detail"), "产品详情")

    def test_taxonomy_covers_studio_and_shared_topics(self):
        self.assertEqual(taxonomy.classify_page("/imaging"), "imaging")
        self.assertEqual(taxonomy.classify_page("/imaging/"), "imaging")
        self.assertEqual(taxonomy.classify_page("/t/123"), "topic_share")
        self.assertEqual(taxonomy.classify_page("/t/not-a-number"), "other")
        self.assertEqual(taxonomy.page_label("imaging"), "显影")
        self.assertEqual(taxonomy.page_label("topic_share"), "帖子分享")

    def test_wechat_wins_over_qq_domain_match(self):
        self.assertEqual(taxonomy.classify_referrer("https://mp.weixin.qq.com/x", "kflow.dev"), "wechat")
        self.assertEqual(taxonomy.classify_referrer("https://im.qq.com/x", "kflow.dev"), "qq")


class VisitSummaryApiTests(VisitStatsBase):
    def login_as_admin(self, level=3):
        session = self.client.session
        session["admin_username"] = "stats-admin"
        session["admin_level"] = level
        session.save()

    def test_anonymous_cannot_read(self):
        self.assertEqual(self.client.get("/api/admin/stats/visits").status_code, 401)

    def test_returns_today_trend_pages_and_sources(self):
        self.visit("/")
        self.visit("/forum", referer="https://www.baidu.com/s?wd=kflow")
        self.login_as_admin()
        response = self.client.get("/api/admin/stats/visits?days=7")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["days"], 7)
        self.assertEqual(len(payload["trend"]), 7)
        self.assertEqual(payload["today"]["pv"], 2)
        self.assertEqual(payload["today"]["uv"], 1)
        labels = {item["label"] for item in payload["top_pages"]}
        self.assertEqual(labels, {"首页", "论坛"})
        source_labels = {item["label"] for item in payload["sources"]}
        self.assertEqual(source_labels, {"直接访问", "百度"})
        self.assertAlmostEqual(sum(item["share"] for item in payload["sources"]), 100.0, places=1)

    def test_range_filter_switches_window(self):
        self.login_as_admin()
        today_payload = self.client.get("/api/admin/stats/visits?range=today").json()
        self.assertEqual((today_payload["range"], today_payload["days"]), ("today", 1))
        self.assertEqual(len(today_payload["trend"]), 1)
        month_payload = self.client.get("/api/admin/stats/visits?range=30d").json()
        self.assertEqual((month_payload["range"], month_payload["days"]), ("30d", 30))
        self.assertEqual(len(month_payload["trend"]), 30)
        legacy = self.client.get("/api/admin/stats/visits?days=999").json()
        self.assertEqual((legacy["range"], legacy["range_label"]), ("all", "全部"))
        bogus = self.client.get("/api/admin/stats/visits?range=bogus&days=oops").json()
        self.assertEqual(bogus["range"], "7d")

    def test_all_range_keeps_old_days_and_buckets_by_week(self):
        old = (timezone.localdate() - timedelta(days=60)).isoformat()
        VisitDaily.objects.create(date=old, pv=4, uv=2)
        VisitPageDaily.objects.create(date=old, page_key="home", pv=4)
        VisitReferrerDaily.objects.create(date=old, source_key="baidu", pv=4)
        VisitVisitor.objects.create(date=old, fingerprint="retained-a")
        VisitVisitor.objects.create(date=old, fingerprint="retained-b")
        self.visit("/")

        self.login_as_admin()
        recent = self.client.get("/api/admin/stats/visits?range=30d").json()
        self.assertEqual(recent["totals"]["pv"], 1)

        payload = self.client.get("/api/admin/stats/visits?range=all").json()
        self.assertEqual(payload["range_label"], "全部")
        self.assertEqual(payload["totals"]["pv"], 5)
        self.assertEqual(payload["totals"]["uv"], 3)
        self.assertEqual(payload["start_date"], old)
        self.assertEqual(payload["bucket"], "week")
        self.assertGreater(len(payload["trend"]), 1)
        self.assertLess(len(payload["trend"]), payload["days"])
        self.assertEqual(sum(item["pv"] for item in payload["trend"]), 5)
        self.assertIn("百度", {item["label"] for item in payload["sources"]})
        self.assertAlmostEqual(payload["totals"]["avg_pv"], round(5 / payload["days"], 1), places=1)

    def test_all_range_without_data_returns_single_bucket(self):
        self.login_as_admin()
        payload = self.client.get("/api/admin/stats/visits?range=all").json()
        self.assertEqual(payload["totals"]["pv"], 0)
        self.assertEqual(len(payload["trend"]), 1)


class RetentionTests(VisitStatsBase):
    def test_cleanup_drops_rows_outside_retention_window(self):
        old = (timezone.localdate() - timedelta(days=120)).isoformat()
        recent = (timezone.localdate() - timedelta(days=10)).isoformat()
        VisitDaily.objects.create(date=old, pv=5, uv=2)
        VisitDaily.objects.create(date=recent, pv=3, uv=1)
        VisitPageDaily.objects.create(date=old, page_key="home", pv=5)
        VisitReferrerDaily.objects.create(date=old, source_key="direct", pv=5)
        VisitVisitor.objects.create(date=old, fingerprint="abc")
        call_command("cleanup_visit_stats")
        self.assertEqual(list(VisitDaily.objects.values_list("date", flat=True)), [recent])
        self.assertFalse(VisitPageDaily.objects.exists())
        self.assertFalse(VisitReferrerDaily.objects.exists())
        self.assertFalse(VisitVisitor.objects.exists())
