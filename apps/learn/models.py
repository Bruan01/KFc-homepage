# pyright: reportMissingImports=false
"""Learn models: vibecoding glossary and tutorials."""
from __future__ import annotations

from django.db import models


class GlossaryTerm(models.Model):
    """A vibecoding term shown on /glossary, each with its own detail page."""

    term = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    en = models.CharField(max_length=120, blank=True, default="")
    definition = models.TextField()  # 列表页的一句话解释
    content_md = models.TextField(blank=True, default="")  # 详情页正文（Markdown）
    category = models.CharField(max_length=32, default="基础概念")
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "glossary_terms"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.term


class Tutorial(models.Model):
    """A vibecoding tutorial or paradigm article on /tutorials."""

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"

    DIFFICULTY_BEGINNER = "beginner"
    DIFFICULTY_INTERMEDIATE = "intermediate"

    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=300, blank=True, default="")
    content_md = models.TextField()
    difficulty = models.CharField(max_length=16, default=DIFFICULTY_BEGINNER)
    kind = models.CharField(max_length=16, default="tutorial")  # tutorial | paradigm
    series = models.CharField(max_length=120, blank=True, default="")
    cover_url = models.CharField(max_length=500, blank=True, default="")
    tags = models.CharField(max_length=256, blank=True, default="")
    sort_order = models.IntegerField(default=0)
    status = models.CharField(max_length=16, default=STATUS_DRAFT)
    views = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tutorials"
        ordering = ["sort_order", "-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def reading_minutes(self) -> int:
        return max(1, len(self.content_md) // 400)


class LearnProgress(models.Model):
    """A user's completion record for a tutorial or glossary term."""

    KIND_TUTORIAL = "tutorial"
    KIND_TERM = "term"

    user = models.ForeignKey(
        "accounts.User",
        db_column="user_id",
        on_delete=models.CASCADE,
        related_name="learn_progress",
    )
    kind = models.CharField(max_length=12)  # tutorial | term
    slug = models.SlugField(max_length=140)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "learn_progress"
        constraints = [
            models.UniqueConstraint(fields=["user", "kind", "slug"], name="uq_learn_progress"),
        ]
        indexes = [models.Index(fields=["user", "kind"])]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.kind}/{self.slug}"
