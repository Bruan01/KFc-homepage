# pyright: reportMissingImports=false
# -*- coding: utf-8 -*-
"""AI 电讯周报：每周一以小K 名义把上周高分资讯整理成论坛精华帖。"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.community_ai.services import official_user
from apps.forum.models import ForumCategory, ForumTopic

from ...models import FeedItem

WEEKLY_BOARD_SLUG = "product"  # 产品版
PER_CATEGORY = 3
WEEKLY_TITLE_PREFIX = "AI 电讯周报"
CATEGORY_LABELS = dict(FeedItem.CATEGORY_CHOICES)


def build_weekly_content(items_by_category, week_label):
    lines = [f"小K 整理了 {week_label} 的 AI 大事，按分类各取评分最高的几条。原文版权归原作者所有，点击链接直达。", ""]
    for category, label in FeedItem.CATEGORY_CHOICES:
        items = items_by_category.get(category) or []
        if not items:
            continue
        lines.append(f"【{label}】")
        for item in items:
            score_bit = f"（评分 {item.score}）" if item.score else ""
            lines.append(f"- {item.title}{score_bit} — {item.upstream_name or item.source.name}")
            lines.append(f"  {item.url}")
        lines.append("")
    lines.append("— 数据来自 AIHOT 公开 API · 实时版见 /feeds")
    return "\n".join(lines)[:20000]


class Command(BaseCommand):
    help = "Publish the weekly AI digest as a forum topic by 小K (idempotent per week)"

    def handle(self, *args, **options):
        official = official_user()
        if not official:
            self.stdout.write(self.style.WARNING("未配置小K 官方账号，跳过周报"))
            return
        category = ForumCategory.objects.filter(slug=WEEKLY_BOARD_SLUG, is_active=True).first()
        if not category:
            self.stdout.write(self.style.WARNING(f"未找到版块 {WEEKLY_BOARD_SLUG}，跳过周报"))
            return

        now = timezone.now()
        week_ago = now - timedelta(days=6)
        if ForumTopic.objects.filter(
            author_username=official.username,
            title__startswith=WEEKLY_TITLE_PREFIX,
            created_at__gte=week_ago,
        ).exists():
            self.stdout.write("本周周报已发布，跳过")
            return

        since = now - timedelta(days=7)
        items_by_category = {}
        for item in (
            FeedItem.objects.filter(published_at__gte=since)
            .exclude(category="")
            .order_by("-score", "-published_at")
        ):
            bucket = items_by_category.setdefault(item.category, [])
            if len(bucket) < PER_CATEGORY:
                bucket.append(item)
        if not any(items_by_category.values()):
            self.stdout.write("上周暂无资讯，跳过周报")
            return

        start = (now - timedelta(days=6)).strftime("%m月%d日")
        end = now.strftime("%m月%d日")
        week_label = f"{start}–{end}"
        topic = ForumTopic.objects.create(
            category=category,
            title=f"{WEEKLY_TITLE_PREFIX} · {week_label}",
            content=build_weekly_content(items_by_category, week_label),
            author_username=official.username,
        )
        self.stdout.write(self.style.SUCCESS(f"周报已发布：{topic.title}（/forum，版块 {category.name}）"))
