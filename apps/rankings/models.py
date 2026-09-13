# pyright: reportMissingImports=false
"""Rankings models: external vibecoding projects and crawl runs."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class ExternalProject(models.Model):
    """A vibecoding project discovered on an external platform (GitHub etc.)."""

    SOURCE_GITHUB = "github"
    SOURCE_PRODUCTHUNT = "producthunt"
    SOURCE_CN_COMMUNITY = "cn_community"

    source = models.CharField(max_length=32)
    external_id = models.CharField(max_length=190)
    title = models.CharField(max_length=256)
    description = models.TextField(blank=True, default="")
    url = models.URLField(max_length=500)
    author = models.CharField(max_length=190, blank=True, default="")
    language = models.CharField(max_length=64, blank=True, default="")
    metrics = models.TextField(blank=True, default="")  # JSON: stars/forks/upvotes/views...
    heat_score = models.FloatField(default=0, db_index=True)
    votes = models.PositiveIntegerField(default=0)  # on-site creativity votes (方案 A)
    summary = models.TextField(blank=True, default="")  # 一句话概括（LLM/规则生成）
    tags = models.TextField(blank=True, default="")  # JSON array，如 ["AI","Agent"]
    analysis = models.TextField(blank=True, default="")  # JSON：产品设计思路剖析
    analysis_source = models.CharField(max_length=8, blank=True, default="")  # llm | rule
    trend_state = models.CharField(max_length=12, blank=True, default="")  # rising/hot/steady/cooling
    analyzed_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    pushed_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_crawled_at = models.DateTimeField()

    class Meta:
        db_table = "external_projects"
        ordering = ["-heat_score", "-votes", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="uq_external_project_source_id"),
        ]
        indexes = [models.Index(fields=["is_active", "-heat_score"])]

    def __str__(self) -> str:
        return f"[{self.source}] {self.title}"


class ExternalProjectVote(models.Model):
    """On-site creativity vote for an external project (one per user)."""

    project = models.ForeignKey(
        ExternalProject,
        on_delete=models.CASCADE,
        related_name="votes_detail",
        db_column="project_id",
    )
    username = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "external_project_votes"
        constraints = [
            models.UniqueConstraint(fields=["project", "username"], name="uq_external_vote_user"),
        ]


class CrawlRun(models.Model):
    """One crawl execution log per source."""

    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    source = models.CharField(max_length=32)
    status = models.CharField(max_length=16, default=STATUS_RUNNING)
    item_count = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "crawl_runs"
        ordering = ["-started_at"]


class ExternalMetricLog(models.Model):
    """Per-crawl metric snapshot backing trend analysis and prediction."""

    project = models.ForeignKey(
        ExternalProject,
        on_delete=models.CASCADE,
        related_name="metric_logs",
        db_column="project_id",
    )
    captured_at = models.DateTimeField(auto_now_add=True)
    heat = models.FloatField(default=0)
    stars = models.PositiveIntegerField(default=0)
    forks = models.PositiveIntegerField(default=0)
    upvotes = models.PositiveIntegerField(default=0)
    replies = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "external_metric_logs"
        ordering = ["captured_at"]
        indexes = [models.Index(fields=["project", "captured_at"])]
