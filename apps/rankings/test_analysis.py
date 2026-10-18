# pyright: reportMissingImports=false
"""Tests for the rankings analysis pipeline (rule channel, trends, detail API)."""
import json
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .analysis import (
    _rule_analysis,
    _rule_summary,
    _rule_tags,
    analyze_top_projects,
    project_trend,
    snapshot_metrics,
    tag_trends,
)
from .models import ExternalMetricLog, ExternalProject


def _make_project(**kwargs):
    defaults = {
        "source": "github",
        "external_id": "test-1",
        "title": "vibe-agent-cli",
        "description": "An AI agent CLI tool for developers, 终端里的智能体",
        "url": "https://github.com/x/vibe-agent-cli",
        "language": "Python",
        "metrics": json.dumps({"stars": 5000, "forks": 300}),
        "heat_score": 500,
        "last_crawled_at": timezone.now(),
    }
    defaults.update(kwargs)
    return ExternalProject.objects.create(**defaults)


class RuleChannelTests(TestCase):
    def setUp(self):
        self.project = _make_project()

    def test_rule_tags_extract_domains(self):
        tags = _rule_tags(self.project)
        self.assertIn("AI", tags)
        self.assertIn("Agent", tags)
        self.assertIn("CLI", tags)

    def test_rule_summary_includes_description_and_heat(self):
        summary = _rule_summary(self.project, {"stars": 5000})
        self.assertIn("An AI agent CLI tool", summary)
        self.assertIn("5,000", summary)

    def test_rule_analysis_fields(self):
        tags = _rule_tags(self.project)
        analysis = _rule_analysis(self.project, tags, {"stars": 5000})
        for key in ("positioning", "audience", "mechanics", "takeaway"):
            self.assertTrue(analysis[key])

    @mock.patch("apps.rankings.analysis._llm_analysis", return_value=None)
    def test_analyze_project_uses_rule_channel(self, _mock_llm):
        analyze_top_projects(force=True, per_source=5)
        self.project.refresh_from_db()
        self.assertEqual(self.project.analysis_source, "rule")
        tags = json.loads(self.project.tags)
        self.assertTrue(tags)
        analysis = json.loads(self.project.analysis)
        self.assertIn("positioning", analysis)

    @mock.patch("apps.rankings.analysis._llm_available", return_value=True)
    @mock.patch(
        "apps.rankings.analysis._llm_analysis",
        return_value={
            "summary": "一个 AI Agent 命令行工具",
            "tags": ["AI", "Agent", "CLI"],
            "analysis": {"positioning": "p", "audience": "a", "mechanics": "m", "takeaway": "t"},
        },
    )
    def test_analyze_project_prefers_llm(self, _mock_llm_analysis, _mock_avail):
        analyze_top_projects(force=True, per_source=5)
        self.project.refresh_from_db()
        self.assertEqual(self.project.analysis_source, "llm")
        self.assertEqual(json.loads(self.project.tags), ["AI", "Agent", "CLI"])


class TrendTests(TestCase):
    def setUp(self):
        self.project = _make_project(metrics=json.dumps({"stars": 1000}))

    def test_snapshot_and_velocity(self):
        now = timezone.now()
        ExternalMetricLog.objects.create(project=self.project, captured_at=now - timezone.timedelta(days=7), stars=1000, heat=400)
        ExternalMetricLog.objects.create(project=self.project, captured_at=now, stars=2000, heat=600)
        trend = project_trend(self.project)
        self.assertEqual(trend["state"], "hot")  # +1000/7d ≈ 143/day >> 20% of 2000
        self.assertGreater(trend["predicted"], 2000)
        self.assertEqual(len(trend["points"]), 2)

    def test_single_snapshot_is_fresh(self):
        snapshot_metrics()
        trend = project_trend(self.project)
        self.assertEqual(trend["state"], "fresh")

    def test_tag_trends_shape(self):
        self.project.tags = json.dumps(["AI", "Agent"], ensure_ascii=False)
        self.project.save(update_fields=["tags"])
        snapshot_metrics()
        data = tag_trends(days=7)
        self.assertIn("tags", data)
        self.assertIn("prediction", data)


class TagTrendsQueryBudgetTests(TestCase):
    """tag_trends 曾经对每个项目单独查一次 ExternalMetricLog（N+1）。

    这批用例把「查询数与项目数无关」钉死：项目翻 3 倍，查询数只能涨 1 条
    （多出来的那条是项目列表本身变长时的分页无关开销，这里用总量上限兜底）。
    """

    def _seed(self, count: int, offset: int = 0):
        now = timezone.now()
        for i in range(count):
            project = ExternalProject.objects.create(
                source="github", external_id=f"n1-{offset + i}", title=f"p{i}",
                url=f"http://x/{i}", author="a", description="d",
                heat_score=float(i), votes=i,
                tags=json.dumps(["AI", "CLI"]),
                metrics=json.dumps({"stars": i}),
                last_crawled_at=now, pushed_at=now,
            )
            for k in range(3):
                ExternalMetricLog.objects.create(
                    project=project, captured_at=now, heat=float(i),
                    stars=i + k, forks=0, upvotes=0, replies=0,
                )

    def _queries(self):
        with CaptureQueriesContext(connection) as ctx:
            tag_trends(days=7)
        return len(ctx.captured_queries)

    def test_query_count_is_flat_when_projects_grow(self):
        self._seed(20)
        base = self._queries()
        self._seed(40, offset=100)
        grown = self._queries()
        self.assertEqual(grown, base, "tag_trends 仍有与项目数相关的 N+1 查询")

    def test_query_count_budget(self):
        self._seed(60)
        self.assertLessEqual(self._queries(), 8)

    def test_same_result_as_naive_per_project_loop(self):
        """批量实现必须和「逐项目查日志」的朴素实现给出同样的聚合结果。"""
        self._seed(15)
        bulk = tag_trends(days=7)
        since = timezone.now() - timedelta(days=7)
        expected: dict[str, dict] = {}
        for project in ExternalProject.objects.filter(is_active=True).exclude(tags=""):
            tags = json.loads(project.tags)
            logs = list(
                ExternalMetricLog.objects.filter(project=project).order_by("captured_at")
            )
            if not logs:
                continue
            now_value = (logs[-1].stars or logs[-1].upvotes or logs[-1].replies or 0)
            past = next((log for log in logs if log.captured_at >= since), logs[0])
            past_value = (past.stars or past.upvotes or past.replies or 0)
            for tag in tags:
                agg = expected.setdefault(tag, {"delta": 0, "now": 0, "projects": 0})
                agg["delta"] += now_value - past_value
                agg["now"] += now_value
                agg["projects"] += 1
        ranked = sorted(expected.items(), key=lambda kv: -kv[1]["delta"])[:8]
        self.assertEqual([t["tag"] for t in bulk["tags"]], [tag for tag, _ in ranked])
        for item, (tag, agg) in zip(bulk["tags"], ranked):
            self.assertEqual(item["delta"], agg["delta"])
            self.assertEqual(item["projects"], agg["projects"])


class DetailAPITests(TestCase):
    def setUp(self):
        self.project = _make_project()
        self.project.summary = "规则摘要"
        self.project.tags = json.dumps(["AI", "CLI"], ensure_ascii=False)
        self.project.analysis = json.dumps({"positioning": "p", "audience": "a", "mechanics": "m", "takeaway": "t"})
        self.project.save(update_fields=["summary", "tags", "analysis"])
        # 相关项目
        _make_project(external_id="test-2", title="related-agent", description="Another AI agent CLI")
        ExternalProject.objects.update_or_create(
            source="github", external_id="test-2",
            defaults={"title": "related-agent", "description": "Another AI agent CLI",
                      "url": "https://github.com/x/related", "heat_score": 100,
                      "tags": json.dumps(["AI", "CLI"]), "last_crawled_at": timezone.now()},
        )

    def test_detail_api(self):
        resp = self.client.get(f"/api/rankings/external/{self.project.pk}")
        self.assertEqual(resp.status_code, 200)
        project = resp.json()["project"]
        self.assertEqual(project["summary"], "规则摘要")
        self.assertIn("AI", project["tags"])
        self.assertEqual(project["analysis"]["positioning"], "p")
        self.assertIn("trend", project)
        self.assertTrue(any(r["title"] == "related-agent" for r in project["related"]))

    def test_detail_404(self):
        resp = self.client.get("/api/rankings/external/99999")
        self.assertEqual(resp.status_code, 404)

    def test_list_includes_tags_and_trend(self):
        resp = self.client.get("/api/rankings/external?source=github")
        item = resp.json()["items"][0]
        self.assertIn("tags", item)
        self.assertIn("trend", item)

    def test_trends_api(self):
        resp = self.client.get("/api/rankings/trends?days=7")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tags", data)
        self.assertIn("prediction", data)
