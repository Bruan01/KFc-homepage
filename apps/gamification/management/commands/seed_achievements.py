# pyright: reportMissingImports=false
"""Seed the community achievements (idempotent)."""
from django.core.management.base import BaseCommand

from apps.gamification.models import Achievement

BADGES = [
    # (code, name, description, icon, tier, category, sort)
    ("first_post", "初来乍到", "发布第 1 篇作品帖", "pencil", "bronze", "creation", 1),
    ("first_reply", "初次开口", "发表第 1 条评论", "bubble", "bronze", "interaction", 2),
    ("first_like", "点赞之交", "第 1 次为他人点赞", "heart", "bronze", "interaction", 3),
    ("regular_3", "常客", "累计活跃 3 天", "clock", "bronze", "activity", 4),
    ("first_vote", "创意投票", "第 1 次为全网榜项目投出创意赞", "sparkle", "bronze", "interaction", 5),
    ("first_boost", "加热新手", "第 1 次给自己的帖子加热", "flame", "bronze", "creation", 6),
    ("author_10", "勤劳作者", "发布 10 篇作品帖", "book", "silver", "creation", 7),
    ("liked_25", "人气成员", "累计获赞 25 次", "heart", "silver", "interaction", 8),
    ("helper_50", "热心同学", "发表 50 条评论", "bubble", "silver", "interaction", 9),
    ("veteran_14", "老朋友", "累计活跃 14 天", "clock", "silver", "activity", 10),
    ("notable_work", "人气作品", "单篇作品获赞 10 次", "star", "silver", "creation", 11),
    ("seller_first", "首单卖家", "在 kflowstore 创作者货架售出第 1 件商品", "bag", "silver", "business", 12),
    ("liked_100", "社区之星", "累计获赞 100 次", "heart", "gold", "interaction", 13),
    ("pillar_500", "中流砥柱", "贡献分达到 500", "trophy", "gold", "activity", 14),
    ("ancient_100", "镇站之宝", "累计活跃 100 天", "clock", "gold", "activity", 15),
    ("famous_work", "传奇作品", "单篇作品获赞 50 次", "star", "gold", "creation", 16),
    ("boost_10", "加热推广官", "累计加热 10 次", "flame", "gold", "business", 17),
    ("voter_50", "意见领袖", "累计投出 50 次创意赞", "sparkle", "gold", "interaction", 18),
    ("active_7", "一周常驻", "累计活跃 7 天", "clock", "bronze", "activity", 20),
    ("author_3", "三作成行", "发布 3 篇作品帖", "pencil", "bronze", "creation", 21),
    ("reply_10", "对话发起人", "发表 10 条评论", "bubble", "bronze", "interaction", 22),
    ("likes_given_10", "友善回应", "累计为他人点赞 10 次", "heart", "bronze", "interaction", 23),
    ("vote_10", "灵感侦察员", "累计投出 10 次创意赞", "sparkle", "bronze", "interaction", 24),
    ("boost_3", "作品推广员", "累计加热 3 次", "flame", "bronze", "business", 25),
    ("active_30", "持之以恒", "累计活跃 30 天", "clock", "silver", "activity", 26),
    ("reply_likes_10", "评论有回响", "评论累计获赞 10 次", "bubble", "silver", "interaction", 27),
    ("notable_work_25", "高光作品", "单篇作品获赞 25 次", "star", "silver", "creation", 28),
    ("study_6", "学习进阶", "完成 6 篇教程", "book", "silver", "activity", 29),
    ("dict_5", "术语入门", "学完 5 个术语词条", "type", "bronze", "activity", 30),
    ("seller_5", "稳定出单", "在 kflowstore 创作者货架售出 5 件商品", "bag", "gold", "business", 31),
    ("contributor_1000", "贡献灯塔", "贡献分达到 1000", "trophy", "gold", "activity", 32),
    ("liked_250", "社区焦点", "累计获赞 250 次", "heart", "gold", "interaction", 33),
    # 板块版主成就
    ("mod_product", "是吗？我收下了", "产品板块版主", "bag", "gold", "activity", 100),
    ("mod_research", "狠狠科研", "科研板块版主", "flask", "gold", "activity", 101),
    ("mod_agent", "塔塔开", "Agent板块版主", "star", "gold", "activity", 102),
    ("mod_hardware", "献祭飞升", "硬件板块版主", "rocket", "gold", "activity", 103),
]

ACHIEVEMENT_CORE = "core_member"  # LV4 人工授予时同步发放的金勋章（随 seed 一并建）


class Command(BaseCommand):
    help = "Seed achievement badges (idempotent)"

    def handle(self, *args, **options):
        created = 0
        for code, name, desc, icon, tier, category, sort in BADGES:
            _, was_created = Achievement.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "description": desc,
                    "icon": icon,
                    "tier": tier,
                    "category": category,
                    "sort_order": sort,
                    "is_active": True,
                },
            )
            created += 1 if was_created else 0
        # LV4 人工授予时同步发放的身份勋章
        _, was_created = Achievement.objects.update_or_create(
            code=ACHIEVEMENT_CORE,
            defaults={
                "name": "核心成员",
                "description": "由管理员授予的 LV4 核心成员身份",
                "icon": "trophy",
                "tier": "gold",
                "category": "activity",
                "sort_order": 19,
                "is_active": True,
            },
        )
        created += 1 if was_created else 0
        self.stdout.write(self.style.SUCCESS(f"achievements: {created} created, {len(BADGES) + 1} total"))
