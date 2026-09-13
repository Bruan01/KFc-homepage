# pyright: reportMissingImports=false
"""Gamification models: achievements, user achievements, user stats snapshots."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class Achievement(models.Model):
    """A badge definition (Stack Overflow style bronze/silver/gold tiers)."""

    TIER_BRONZE = "bronze"
    TIER_SILVER = "silver"
    TIER_GOLD = "gold"
    TIER_CHOICES = (
        (TIER_BRONZE, "铜"),
        (TIER_SILVER, "银"),
        (TIER_GOLD, "金"),
    )

    CATEGORY_CHOICES = (
        ("creation", "创作"),
        ("interaction", "互动"),
        ("activity", "活跃"),
        ("business", "商务"),
    )

    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=200, blank=True, default="")
    icon = models.CharField(max_length=32, default="star")  # kflowIcons name
    tier = models.CharField(max_length=8, choices=TIER_CHOICES, default=TIER_BRONZE)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default="interaction")
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "achievements"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.name}({self.code})"


class UserAchievement(models.Model):
    """One granted badge per user per achievement (idempotent)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="user_id",
        on_delete=models.CASCADE,
        related_name="achievements",
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        related_name="grants",
    )
    granted_by = models.CharField(max_length=150, default="system")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_achievements"
        ordering = ["-granted_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "achievement"], name="uq_user_achievement"),
        ]


class UserStats(models.Model):
    """Per-user activity counters, refreshed hourly by refresh_gamification."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        db_column="user_id",
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="community_stats",
    )
    active_days = models.PositiveIntegerField(default=0)
    topics = models.PositiveIntegerField(default=0)
    replies = models.PositiveIntegerField(default=0)
    likes_given = models.PositiveIntegerField(default=0)
    likes_received = models.PositiveIntegerField(default=0)  # topic likes
    reply_likes_received = models.PositiveIntegerField(default=0)
    votes_cast = models.PositiveIntegerField(default=0)
    boosts_bought = models.PositiveIntegerField(default=0)
    listings_sold = models.PositiveIntegerField(default=0)
    max_topic_likes = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_stats"

    @property
    def total_likes_received(self) -> int:
        return self.likes_received + self.reply_likes_received
