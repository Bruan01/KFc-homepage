# pyright: reportMissingImports=false
# -*- coding: utf-8 -*-
"""小K AI 早报：每天把昨日高分资讯推送到全站通知，点开直达 /feeds。"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.community_ai.services import official_user
from apps.notifications.models import Notification

from ...models import FeedItem

TOP_N = 5


def daily_recipients():
    """真实用户：排除每日虚拟成员（community_guest_*）和小K 官方号。"""
    official = official_user()
    qs = User.objects.exclude(username__startswith="community_guest_")
    if official:
        qs = qs.exclude(pk=official.pk)
    return list(qs)


def build_digest():
    """过去 24 小时评分最高的 N 条；不足时按时间倒序补齐。"""
    since = timezone.now() - timedelta(hours=24)
    base = FeedItem.objects.filter(published_at__gte=since)
    items = list(base.order_by("-score", "-published_at")[:TOP_N])
    if len(items) < TOP_N:
        items = list(FeedItem.objects.order_by("-published_at")[:TOP_N])
    return items


class Command(BaseCommand):
    help = "Push the daily AI digest notification to all real users (idempotent per day)"

    def handle(self, *args, **options):
        today = timezone.localdate()
        already = Notification.objects.filter(
            type="feed",
            actor_username="xiaok-daily",
            created_at__date=today,
        ).exists()
        if already:
            self.stdout.write(f"早报已推送过（{today}），跳过")
            return

        items = build_digest()
        if not items:
            self.stdout.write("暂无资讯，跳过早报")
            return

        date_label = f"{today.month}月{today.day}日"
        title = f"小K AI 早报 · {date_label}"
        body = " / ".join(item.title[:28] for item in items[:3])
        if len(items) > 3:
            body += f" 等 {len(items)} 条"
        body = body[:300]

        recipients = daily_recipients()
        Notification.objects.bulk_create(
            Notification(
                recipient=user,
                type="feed",
                title=title,
                body=body,
                link="/feeds",
                actor_username="xiaok-daily",
            )
            for user in recipients
        )
        self.stdout.write(self.style.SUCCESS(f"早报已推送给 {len(recipients)} 位用户（{date_label}，{len(items)} 条精选）"))
