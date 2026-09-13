# pyright: reportMissingImports=false
"""Management command to seed default forum categories."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.forum.models import ForumCategory

DEFAULTS = [
    {"slug": "showcase",   "name": "晒作品", "icon": "晒", "color": "#d9232e", "sort_order": 1},
    {"slug": "review",     "name": "求点评", "icon": "评", "color": "#a66713", "sort_order": 2},
    {"slug": "oneshot",    "name": "一句话应用", "icon": "句", "color": "#7254b8", "sort_order": 3},
    {"slug": "tips",       "name": "工具技巧", "icon": "巧", "color": "#2563a8", "sort_order": 4},
    {"slug": "pitfalls",   "name": "踩坑记录", "icon": "坑", "color": "#657080", "sort_order": 5},
    {"slug": "collab",     "name": "招募合作", "icon": "合", "color": "#16805b", "sort_order": 6},
]


class Command(BaseCommand):
    help = "Seed default KFlow forum categories (idempotent)."

    def handle(self, *args, **options):
        created = 0
        for data in DEFAULTS:
            _, was_created = ForumCategory.objects.update_or_create(
                slug=data["slug"],
                defaults={k: v for k, v in data.items() if k != "slug"} | {"is_active": True},
            )
            if was_created:
                created += 1
        # deactivate legacy categories that are no longer part of the set,
        # keeping their rows intact so existing topics keep their FK
        default_slugs = {data["slug"] for data in DEFAULTS}
        retired = ForumCategory.objects.exclude(slug__in=default_slugs).filter(is_active=True)
        retired_count = retired.update(is_active=False)
        self.stdout.write(self.style.SUCCESS(
            f"Forum categories seeded: {created} created, {len(DEFAULTS) - created} updated, {retired_count} deactivated."
        ))
