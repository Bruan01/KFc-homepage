"""Self-hosted visit counters.

只存聚合结果和不可逆的访客指纹：没有原始 IP、UA、完整 URL 参数。
"""
from __future__ import annotations

from django.db import models


class VisitDaily(models.Model):
    """每天一行的总量：PV 为页面浏览次数，UV 为去重访客数。"""

    date = models.CharField(max_length=10, unique=True)
    pv = models.PositiveIntegerField(default=0)
    uv = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "visit_daily"
        ordering = ["-date"]


class VisitPageDaily(models.Model):
    """按页面分组的每日 PV；page_key 是站点页面标识，不是原始 URL。"""

    date = models.CharField(max_length=10)
    page_key = models.CharField(max_length=64)
    pv = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "visit_page_daily"
        ordering = ["-date", "-pv"]
        constraints = [
            models.UniqueConstraint(fields=["date", "page_key"], name="uniq_visit_page_day"),
        ]


class VisitReferrerDaily(models.Model):
    """来源渠道每日 PV：direct/internal/站点标识，未知外站存域名。"""

    date = models.CharField(max_length=10)
    source_key = models.CharField(max_length=120)
    pv = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "visit_referrer_daily"
        ordering = ["-date", "-pv"]
        constraints = [
            models.UniqueConstraint(fields=["date", "source_key"], name="uniq_visit_referrer_day"),
        ]


class VisitVisitor(models.Model):
    """当天出现过的访客指纹，仅用于 UV 去重与留存期内的跨日统计。"""

    date = models.CharField(max_length=10)
    fingerprint = models.CharField(max_length=40)

    class Meta:
        db_table = "visit_visitors"
        indexes = [models.Index(fields=["date"], name="idx_visit_visitors_date")]
        constraints = [
            models.UniqueConstraint(fields=["date", "fingerprint"], name="uniq_visit_visitor_day"),
        ]
