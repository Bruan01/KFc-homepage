# pyright: reportMissingImports=false
"""Feeds models: curated AI sources (directory) and aggregated feed items."""
from __future__ import annotations

from django.db import models


class FeedSource(models.Model):
    """A curated AI information source.

    Doubles as the directory entry (site_url/description) and, when
    ``feed_url`` is set, as an RSS/Atom source the fetcher aggregates.
    """

    CATEGORY_OFFICIAL = "official"
    CATEGORY_MEDIA = "media"
    CATEGORY_CHINA = "china"
    CATEGORY_COMMUNITY = "community"
    CATEGORY_RESEARCH = "research"
    CATEGORY_AGGREGATOR = "aggregator"
    CATEGORY_CHOICES = [
        (CATEGORY_OFFICIAL, "一手官方"),
        (CATEGORY_MEDIA, "海外媒体"),
        (CATEGORY_CHINA, "中文媒体"),
        (CATEGORY_COMMUNITY, "社区热榜"),
        (CATEGORY_RESEARCH, "论文研究"),
        (CATEGORY_AGGREGATOR, "聚合导航"),
    ]

    name = models.CharField(max_length=190)
    slug = models.CharField(max_length=64, unique=True)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES)
    site_url = models.URLField(max_length=500)
    feed_url = models.URLField(max_length=500, blank=True, default="")  # 空 = 仅目录展示，不抓取
    fetch_kind = models.CharField(max_length=16, default="rss")  # rss | api_aihot
    description = models.CharField(max_length=300, blank=True, default="")
    language = models.CharField(max_length=8, default="zh")  # zh | en
    icon = models.CharField(max_length=8, default="📰")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "feed_sources"
        ordering = ["sort_order", "id"]
        indexes = [models.Index(fields=["category", "is_active"])]

    def __str__(self) -> str:
        return f"[{self.category}] {self.name}"


class FeedItem(models.Model):
    """One aggregated entry (title + link + summary, always linking back).

    资讯主体来自 AIHOT 公开 API（已做 AI 相关性筛选与中文摘要），
    保留其分类/评分/上游信源名； attribution 始终链回 AIHOT 与原文。
    """

    # 条目级分类（AIHOT 词表，timeline 筛选用）
    CATEGORY_MODEL = "model"
    CATEGORY_PRODUCT = "product"
    CATEGORY_INDUSTRY = "industry"
    CATEGORY_PAPER = "paper"
    CATEGORY_TIP = "tip"
    CATEGORY_OPINION = "opinion"
    CATEGORY_CHOICES = [
        (CATEGORY_MODEL, "模型"),
        (CATEGORY_PRODUCT, "产品"),
        (CATEGORY_INDUSTRY, "行业"),
        (CATEGORY_PAPER, "论文"),
        (CATEGORY_TIP, "教程"),
        (CATEGORY_OPINION, "观点"),
    ]

    source = models.ForeignKey(
        FeedSource,
        on_delete=models.CASCADE,
        related_name="items",
        db_column="source_id",
    )
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1000)
    summary = models.CharField(max_length=1000, blank=True, default="")
    guid = models.CharField(max_length=500)  # RSS <guid> / Atom <id> / AIHOT item id
    language = models.CharField(max_length=8, default="")
    published_at = models.DateTimeField()
    category = models.CharField(max_length=16, blank=True, default="")  # 条目级分类（AIHOT 词表）
    is_selected = models.BooleanField(default=False)  # AIHOT 精选标记（mode=all 里 selected=true 的条目）
    score = models.PositiveSmallIntegerField(default=0)  # AIHOT AI 评分 0-100
    upstream_name = models.CharField(max_length=190, blank=True, default="")  # 上游信源名（如 "X：OpenAI"）
    via_name = models.CharField(max_length=64, blank=True, default="")  # 聚合出处（AIHOT）
    via_url = models.URLField(max_length=500, blank=True, default="")
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feed_items"
        ordering = ["-published_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "guid"], name="uq_feed_item_source_guid"),
        ]
        indexes = [
            models.Index(fields=["-published_at"], name="feed_item_published_idx"),
            models.Index(fields=["category"], name="feed_item_category_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source.slug}: {self.title[:50]}"


class FeedFetchRun(models.Model):
    """One fetch execution log per source (failure isolation, like crawl_runs)."""

    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    source_slug = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default=STATUS_RUNNING)
    item_count = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "feed_fetch_runs"
        ordering = ["-started_at"]
