# pyright: reportMissingImports=false
"""Tests for learn (glossary + tutorials) APIs."""
from django.test import TestCase

from .constants import BOOK_PAGE_SEPARATOR
from .models import GlossaryTerm, Tutorial
from .tutorials_data import TUTORIALS


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
            content_md=f"# 标题\n\n正文{BOOK_PAGE_SEPARATOR}## 第二页\n\n继续学习",
            difficulty="beginner",
            kind="tutorial",
            status=Tutorial.STATUS_PUBLISHED,
            sort_order=1,
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
        self.assertEqual(items[0]["chapter_number"], 1)
        self.assertEqual(items[0]["page_count"], 2)
        self.assertEqual(resp.json()["book"]["chapter_count"], 1)
        self.assertEqual(resp.json()["book"]["page_count"], 2)

    def test_detail_renders_and_counts_views(self):
        resp = self.client.get("/api/learn/tutorials/hello")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# 标题", resp.json()["tutorial"]["content_md"])
        self.assertEqual(resp.json()["tutorial"]["page_count"], 2)
        self.assertEqual(len(resp.json()["tutorial"]["pages"]), 2)
        self.assertIsInstance(resp.json()["tutorial"]["pages"][0], str)
        self.assertIsNone(resp.json()["tutorial"]["previous_chapter"])
        self.assertIsNone(resp.json()["tutorial"]["next_chapter"])
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


class TutorialBookDataTests(TestCase):
    def test_book_contains_sixteen_unique_paginated_chapters(self):
        self.assertEqual(len(TUTORIALS), 16)
        self.assertEqual(len({chapter["slug"] for chapter in TUTORIALS}), 16)
        self.assertEqual(
            {chapter["series"] for chapter in TUTORIALS},
            {"第一卷 · 思维与需求", "第二卷 · 工具与上下文", "第三卷 · 工程实现", "第四卷 · 质量与交付", "第五卷 · 持续演进"},
        )
        for chapter in TUTORIALS:
            self.assertGreaterEqual(chapter["content_md"].count(BOOK_PAGE_SEPARATOR), 2, chapter["slug"])
            self.assertIn("## 延伸阅读", chapter["content_md"], chapter["slug"])
