# pyright: reportMissingImports=false
"""LRobotcup 后端改造：碎碎念 GET /api/murmurs 的 q 关键词过滤。

TestCase 用临时测试库，不触碰 data/homepage.db。
"""
from django.test import TestCase

from apps.accounts.models import User

from .models import Murmur


class MurmurKeywordFilterTests(TestCase):
    """q 对 content 做 icontains，用于「具身智能打卡」垂直流。"""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            username="lrc_alice", password="pass1234", email="a@example.com",
            created_at="2026-01-01T00:00:00+00:00",
        )

    def setUp(self):
        Murmur.objects.create(
            author_username=self.alice.username,
            content="具身智能打卡：今天用 LeRobot 跑通了 ACT 策略",
            client_key="lrc-k1", channel="daily",
        )
        Murmur.objects.create(
            author_username=self.alice.username,
            content="具身智能打卡：读完一篇 VLA 论文",
            client_key="lrc-k2", channel="daily",
        )
        Murmur.objects.create(
            author_username=self.alice.username,
            content="周末爬山，天气不错",
            client_key="lrc-k3", channel="daily",
        )

    def test_q_filters_content_and_is_guest_accessible(self):
        resp = self.client.get("/api/murmurs", {"q": "具身智能打卡"})
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertIn("具身智能打卡", item["content"])

    def test_q_absent_returns_all(self):
        resp = self.client.get("/api/murmurs")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["items"]), 3)

    def test_q_with_no_match_returns_empty(self):
        resp = self.client.get("/api/murmurs", {"q": "完全不存在的关键词"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["items"], [])
