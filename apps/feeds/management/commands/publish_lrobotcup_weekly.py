# pyright: reportMissingImports=false
# -*- coding: utf-8 -*-
"""具身智能周报：每周一以小K 名义把近 7 天的具身智能信源条目汇总成论坛帖。

照抄 publish_feed_weekly.py 的范式：official_user() + 按周幂等 +
ForumTopic.objects.create()。标题带 ISO 年份周数，同一周重复执行不重复发帖；
近期无条目时跳过、不发空帖。
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.community_ai.services import official_user
from apps.forum.models import ForumCategory, ForumTopic

from ...models import FeedItem

BOARD_SLUG = "embodied-ai"
CATEGORY = "embodied-ai"  # FeedSource.category；周报据此圈定信源
WEEKLY_TITLE_PREFIX = "具身智能行业周报"
TOPIC_TAGS = "具身智能,行业动态,周报"
LOOKBACK_DAYS = 7
# 一周可能聚合上百条（arXiv / 厂商博客量很大），帖子只放最近 30 条，
# 否则会被 20000 字上限截断在半个链接里，读起来像损坏的内容。
MAX_POST_ITEMS = 30


def _fmt_published(value):
    """把条目的发布时间格式化为本地时间字符串；兼容空值。"""
    if not value:
        return "未知"
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%Y-%m-%d %H:%M")


def build_weekly_content(items, week_label, total=None):
    total = len(items) if total is None else total
    lines = [
        f"小K 整理了 {week_label} 聚合到的具身智能行业动态，共 {total} 条，"
        f"下面按发布时间倒序展示最近 {len(items)} 条。"
        "以下条目来自社区订阅的信源，原文版权归原作者所有，点击链接直达。",
        "",
    ]
    for item in items:
        source_name = item.upstream_name or item.source.name
        lines.append(f"### {item.title}")
        lines.append(f"- 来源：{source_name}")
        lines.append(f"- 发布时间：{_fmt_published(item.published_at)}")
        lines.append(f"- 原文链接：{item.url}")
        if item.summary:
            lines.append("")
            lines.append(f"> {item.summary}")
        lines.append("")
    if total > len(items):
        lines.append(f"> 其余 {total - len(items)} 条可在专题页「行业动态」里按信源查看。")
        lines.append("")
    lines.append("— 本贴由服务端定时任务自动生成 · 实时动态见 /forum/lrobotcup 与 /feeds")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Publish the embodied-AI weekly digest as a forum topic by 小K (idempotent per ISO week)"

    def handle(self, *args, **options):
        official = official_user()
        if not official:
            self.stdout.write(self.style.WARNING("未配置小K 官方账号，跳过具身智能周报"))
            return
        category = ForumCategory.objects.filter(slug=BOARD_SLUG, is_active=True).first()
        if not category:
            self.stdout.write(self.style.WARNING(f"未找到版块 {BOARD_SLUG}，跳过具身智能周报"))
            return

        now = timezone.now()
        iso_year, iso_week, _ = now.isocalendar()
        week_label = f"{iso_year} 年第 {iso_week:02d} 周"
        title = f"{WEEKLY_TITLE_PREFIX} · {week_label}"
        # 按周幂等：标题含年份周数，精确匹配即可保证「同一周只发一篇」。
        if ForumTopic.objects.filter(author_username=official.username, title=title).exists():
            self.stdout.write("本周具身智能周报已发布，跳过")
            return

        since = now - timedelta(days=LOOKBACK_DAYS)
        # 具身智能归类落在信源上（FeedSource.category="embodied-ai"）；
        # FeedItem.category 是 AIHOT 词表，lrc- 信源抓取的条目该项为空。
        # 同时兼容两种写法，避免漏聚合。
        items = list(
            FeedItem.objects.filter(
                Q(category=CATEGORY) | Q(source__category=CATEGORY),
                published_at__gte=since,
            ).select_related("source").order_by("-published_at", "-id")
        )
        if not items:
            self.stdout.write("近 7 天暂无具身智能新条目，跳过周报（不发空帖）")
            return

        with transaction.atomic():
            topic = ForumTopic.objects.create(
                category=category,
                title=title,
                content=build_weekly_content(items[:MAX_POST_ITEMS], week_label, total=len(items)),
                author_username=official.username,
                tags=TOPIC_TAGS,
                status=ForumTopic.STATUS_OPEN,
            )
        self.stdout.write(self.style.SUCCESS(
            f"具身智能周报已发布：{topic.title}（{len(items)} 条，版块 {category.name}）"
        ))
