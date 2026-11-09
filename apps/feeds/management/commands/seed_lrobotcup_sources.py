# pyright: reportMissingImports=false
# -*- coding: utf-8 -*-
"""幂等写入具身智能信源（slug 前缀 lrc-，category=embodied-ai）。

数据来源：output/lrc-news-seed.json 的 sources 数组。
只写 services.fetch_source 真正支持的 fetch_kind：
  - rss / atom 都走 parse_feed（同时兼容 RSS 2.0 与 Atom XML），统一存 rss；
  - api_aihot 走 AIHOT 专用分支（本批信源未使用）；
  - api（如 GitHub REST JSON）parse_feed 无法解析，跳过并输出说明，
    不硬塞导致 fetch 报错。
已存在的 slug 只同步内容字段，不重复创建、不动 last_fetched_at 等运营状态。
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from ...models import FeedSource

SEED_FILE = Path(settings.BASE_DIR) / "output" / "lrc-news-seed.json"
SLUG_PREFIX = "lrc-"
CATEGORY = "embodied-ai"
# JSON 里的 feedKind -> 数据库 fetch_kind。None 表示不支持、跳过。
KIND_MAP = {
    "rss": "rss",
    "atom": "rss",  # parse_feed 同时解析 Atom，fetch_kind 非 api_aihot 即走该分支
    "api": None,    # GitHub REST API 返回 JSON，parse_feed 无法解析
}


class Command(BaseCommand):
    help = "幂等写入具身智能 FeedSource（lrc- 前缀，category=embodied-ai）"

    def handle(self, *args, **options):
        payload = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        sources = payload.get("sources", [])
        created = updated = skipped = 0
        with transaction.atomic():
            for entry in sources:
                raw_kind = (entry.get("feedKind") or "").lower()
                if raw_kind not in KIND_MAP or KIND_MAP[raw_kind] is None:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(
                        f"跳过 {entry.get('slug')}：feedKind={raw_kind or '空'} 不受支持"
                        f"（parse_feed 仅解析 RSS/Atom XML，api 类 JSON 未接入），不写入以免 fetch 报错"
                    ))
                    continue
                fetch_kind = KIND_MAP[raw_kind]
                slug = SLUG_PREFIX + entry["slug"]
                defaults = {
                    "name": entry["name"],
                    "category": CATEGORY,
                    "site_url": entry["siteUrl"],
                    "feed_url": entry.get("feedUrl", ""),
                    "fetch_kind": fetch_kind,
                    "description": (entry.get("note") or "")[:300],
                    "language": entry.get("language", "en"),
                    "icon": "🤖",
                    "is_active": True,
                }
                source, was_created = FeedSource.objects.get_or_create(
                    slug=slug, defaults=defaults,
                )
                if was_created:
                    created += 1
                    continue
                # 已存在的源只同步内容字段；is_active/last_fetched_at 等运营状态不动。
                changed = False
                for field in ("name", "category", "site_url", "feed_url",
                              "fetch_kind", "description", "language", "icon"):
                    new_value = defaults[field]
                    if getattr(source, field) != new_value:
                        setattr(source, field, new_value)
                        changed = True
                if changed:
                    source.save()
                    updated += 1
        total = FeedSource.objects.filter(slug__startswith=SLUG_PREFIX).count()
        self.stdout.write(self.style.SUCCESS(
            f"具身智能信源：{created} 新建，{updated} 更新，{skipped} 跳过（不支持的 kind），"
            f"lrc- 信源共 {total} 条"
        ))
