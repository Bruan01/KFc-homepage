# pyright: reportMissingImports=false
"""Management command to seed default forum categories."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.forum.models import ForumCategory

DEFAULTS = [
    {"slug": "announcements", "name": "产品动态", "icon": "新", "color": "#d9232e", "sort_order": 1},
    {"slug": "tech",          "name": "技术交流", "icon": "码", "color": "#2563a8", "sort_order": 2},
    {"slug": "help",          "name": "使用帮助", "icon": "?",  "color": "#a66713", "sort_order": 3},
    {"slug": "resources",     "name": "资源分享", "icon": "享", "color": "#16805b", "sort_order": 4},
    {"slug": "showcase",      "name": "项目展示", "icon": "作", "color": "#7254b8", "sort_order": 5},
    {"slug": "general",       "name": "闲聊广场", "icon": "聊", "color": "#657080", "sort_order": 6},
]


class Command(BaseCommand):
    help = "Seed default KFlow forum categories (idempotent)."

    def handle(self, *args, **options):
        created = 0
        for data in DEFAULTS:
            _, was_created = ForumCategory.objects.get_or_create(
                slug=data["slug"],
                defaults={k: v for k, v in data.items() if k != "slug"},
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f"Forum categories seeded: {created} created, {len(DEFAULTS) - created} already existed."
        ))
