# pyright: reportMissingImports=false
"""Seed glossary terms (each with detail page) and detailed tutorials (idempotent)."""
from django.core.management.base import BaseCommand

from apps.learn.glossary_data import GLOSSARY
from apps.learn.models import GlossaryTerm, Tutorial
from apps.learn.tutorials_data import TUTORIALS


class Command(BaseCommand):
    help = "Seed glossary terms and detailed tutorials"

    def handle(self, *args, **options):
        created_terms = 0
        for slug, term, en, category, definition, content_md, order in GLOSSARY:
            _, was_created = GlossaryTerm.objects.update_or_create(
                slug=slug,
                defaults={
                    "term": term,
                    "en": en,
                    "definition": definition,
                    "content_md": content_md,
                    "category": category,
                    "sort_order": order,
                    "is_active": True,
                },
            )
            created_terms += 1 if was_created else 0

        created_tutorials = 0
        for data in TUTORIALS:
            _, was_created = Tutorial.objects.update_or_create(
                slug=data["slug"],
                defaults={k: v for k, v in data.items() if k != "slug"} | {"status": Tutorial.STATUS_PUBLISHED},
            )
            created_tutorials += 1 if was_created else 0

        # 学习类成就勋章
        from apps.gamification.models import Achievement

        total_tutorials = len(TUTORIALS)
        total_terms = len(GLOSSARY)
        learning_badges = [
            ("late_start", "从现在开始就不晚", "完成第 1 篇教程——学习永远不晚", "book", "bronze", "activity"),
            ("study_3", "求知若渴", "完成 3 篇教程", "book", "silver", "activity"),
            ("graduate_all", "学有所成", f"完成全部 {total_tutorials} 篇教程", "trophy", "gold", "activity"),
            ("dict_10", "行走的词典", "学完 10 个术语词条", "type", "silver", "activity"),
            ("dict_all", "概念百科", f"学完全部 {total_terms} 个术语词条", "sparkle", "gold", "activity"),
        ]
        from django.core.management.base import OutputWrapper
        badge_created = 0
        for code, name, desc, icon, tier, category in learning_badges:
            _, was_created = Achievement.objects.update_or_create(
                code=code,
                defaults={"name": name, "description": desc, "icon": icon, "tier": tier,
                          "category": category, "sort_order": 40, "is_active": True},
            )
            badge_created += 1 if was_created else 0

        self.stdout.write(self.style.SUCCESS(
            f"glossary: {created_terms} created ({len(GLOSSARY)} total); tutorials: {created_tutorials} created ({len(TUTORIALS)} total); learning badges: {badge_created} created"
        ))
