# pyright: reportMissingImports=false
# -*- coding: utf-8 -*-
"""Seed curated AI feed sources (idempotent, mirrors seed_achievements style)."""
from django.core.management.base import BaseCommand

from ...models import FeedItem, FeedSource
from ...sources import SOURCES


class Command(BaseCommand):
    help = "Seed/update curated AI feed sources (idempotent)"

    def handle(self, *args, **options):
        created = updated = 0
        for data in SOURCES:
            source, was_created = FeedSource.objects.get_or_create(
                slug=data["slug"],
                defaults={
                    "name": data["name"],
                    "category": data["category"],
                    "site_url": data["site_url"],
                    "feed_url": data.get("feed_url", ""),
                    "fetch_kind": data.get("fetch_kind", "rss"),
                    "description": data.get("description", ""),
                    "language": data.get("language", "zh"),
                    "icon": data.get("icon", "📰"),
                    "sort_order": data.get("sort_order", 100),
                },
            )
            if was_created:
                created += 1
                continue
            # 已存在的源只同步内容字段；is_active/last_fetched_at 等运营状态不动。
            changed = False
            for field in ("name", "category", "site_url", "feed_url", "fetch_kind", "description", "language", "icon", "sort_order"):
                new_value = data.get(field, "" if field in ("feed_url", "description") else None)
                if new_value is None:
                    continue
                if getattr(source, field) != new_value:
                    setattr(source, field, new_value)
                    changed = True
            if changed:
                source.save()
                updated += 1
        # 停止直连抓取的信源（feed_url 清空）留下的旧条目已过期或与 AIHOT 重复，清掉。
        stale_slugs = [s["slug"] for s in SOURCES if not s.get("feed_url")]
        deleted, _ = FeedItem.objects.filter(source__slug__in=stale_slugs).delete()
        total = FeedSource.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"feed sources: {created} created, {updated} updated, {total} total"
                + (f", {deleted} stale items pruned" if deleted else "")
            )
        )
