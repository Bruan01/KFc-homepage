# pyright: reportMissingImports=false
"""Tests for learn (glossary + tutorials) APIs."""
from django.test import TestCase

from .models import GlossaryTerm, Tutorial


class GlossaryTests(TestCase):
    def setUp(self):
        GlossaryTerm.objects.create(slug="vibe-coding", term="氛围编程", en="Vibe Coding", definition="用自然语言让 AI 写代码", category="基础概念", sort_order=1)
        GlossaryTerm.objects.create(slug="mcp", term="MCP", en="Model Context Protocol", definition="AI 工具接入外部服务的协议", category="工具", sort_order=2)
        GlossaryTerm.objects.create(slug="hidden", term="隐藏术语", en="Hidden", definition="不应出现", category="工具", sort_order=3, is_active=False)

    def test_glossary_lists_active_only(self):
        resp = self.client.get("/api/learn/glossary")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertEqual(len(items), 2)

    def test_glossary_detail_api(self):
        resp = self.client.get("/api/learn/glossary/vibe-coding")
        self.assertEqual(resp.status_code, 200)
        term = resp.json()["term"]
        self.assertEqual(term["slug"], "vibe-coding")
        self.assertIsInstance(term["related"], list)

    def test_glossary_detail_404(self):
        resp = self.client.get("/api/learn/glossary/nope")
        self.assertEqual(resp.status_code, 404)

    def test_category_filter(self):
        resp = self.client.get("/api/learn/glossary?category=工具")
        items = resp.json()["items"]
        self.assertEqual([item["term"] for item in items], ["MCP"])


class TutorialTests(TestCase):
    def setUp(self):
        Tutorial.objects.create(
            slug="hello",
            title="第一个教程",
            summary="入门",
            content_md="# 标题\n\n正文",
            difficulty="beginner",
            kind="tutorial",
            status=Tutorial.STATUS_PUBLISHED,
        )
        Tutorial.objects.create(
            slug="draft",
            title="草稿教程",
            content_md="draft",
            status=Tutorial.STATUS_DRAFT,
        )

    def test_list_shows_published_only(self):
        resp = self.client.get("/api/learn/tutorials")
        items = resp.json()["items"]
        self.assertEqual([item["slug"] for item in items], ["hello"])
        self.assertEqual(items[0]["reading_minutes"], 1)

    def test_detail_renders_and_counts_views(self):
        resp = self.client.get("/api/learn/tutorials/hello")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# 标题", resp.json()["tutorial"]["content_md"])
        tutorial = Tutorial.objects.get(slug="hello")
        tutorial.refresh_from_db()
        self.assertEqual(tutorial.views, 1)

    def test_detail_404_for_draft(self):
        resp = self.client.get("/api/learn/tutorials/draft")
        self.assertEqual(resp.status_code, 404)

    def test_kind_filter(self):
        Tutorial.objects.create(
            slug="paradigm-one",
            title="一句话范式",
            content_md="x",
            kind="paradigm",
            status=Tutorial.STATUS_PUBLISHED,
        )
        resp = self.client.get("/api/learn/tutorials?kind=paradigm")
        self.assertEqual([item["slug"] for item in resp.json()["items"]], ["paradigm-one"])
