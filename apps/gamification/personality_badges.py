"""Local, idempotent personality collectibles. Never calls a model or auto-equips."""
from django.db import transaction
from django.db.models import F
from django.db.models.expressions import RawSQL

from .models import Achievement, UserAchievement, UserStats


PERSONALITIES = (
    ("INTJ", "星图构筑", "compass"), ("INTP", "思绪轨道", "sparkle"),
    ("ENTJ", "远航领路", "flag"), ("ENTP", "灵感分岔", "sparkle"),
    ("INFJ", "静夜寻光", "lamp"), ("INFP", "心间拾光", "feather"),
    ("ENFJ", "向阳相伴", "sun"), ("ENFP", "灵感漫游", "sparkle"),
    ("ISTJ", "秩序书页", "book"), ("ISFJ", "温柔守望", "shield"),
    ("ESTJ", "筑序前行", "check"), ("ESFJ", "花间相聚", "heart"),
    ("ISTP", "巧思造物", "gear"), ("ISFP", "随心绘色", "pencil"),
    ("ESTP", "逐风而行", "bolt"), ("ESFP", "此刻闪耀", "music"),
)
BADGE_ROWS = [
    (f"mbti-{kind.lower()}", f"{kind} · {title}",
     f"完成心映测评，获得 {kind} 人格探索结果。", icon, "identity", "personality", 200 + i)
    for i, (kind, title, icon) in enumerate(PERSONALITIES)
]
VALID_TYPES = {kind for kind, _, _ in PERSONALITIES}


def sync_personality_badges(user):
    """Keep exactly the newest completed assessment's type, without exposing it by default."""
    from apps.personality.models import Assessment

    with transaction.atomic():
        # First acquire SQLite's writer reservation, then read the latest report.
        # This also works when no stats row exists; select_for_update does not lock SQLite.
        UserStats.objects.filter(user=user).update(updated_at=F("updated_at"))
        # Windows may stamp multiple inserts with the same clock tick. UUID order
        # is random; SQLite insertion order is the tie-breaker, not completion time.
        report = Assessment.objects.filter(user=user, status="completed").annotate(
            creation_order=RawSQL('"personality_assessments"."rowid"', ())
        ).order_by("-created_at", "-creation_order").values_list("report", flat=True).first()
        kind = report.get("type") if isinstance(report, dict) else None
        kind = kind if isinstance(kind, str) and kind in VALID_TYPES else None
        current = None
        for code, name, description, icon, tier, category, order in BADGE_ROWS:
            if code[5:].upper() != kind:
                continue
            badge, _ = Achievement.objects.get_or_create(code=code, defaults={
                "name": name, "description": description, "icon": icon,
                "tier": tier, "category": category, "sort_order": order,
            })
            if badge.is_active:
                UserAchievement.objects.get_or_create(user=user, achievement=badge)
                current = badge
        old = UserAchievement.objects.filter(user=user, achievement__code__startswith="mbti-")
        worn = UserStats.objects.filter(user=user, showcase__code__startswith="mbti-")
        if current:
            old = old.exclude(achievement=current)
            worn = worn.exclude(showcase=current)
        # An already public MBTI follows the new result; other badges and hidden state stay intact.
        worn.update(showcase=current)
        old.delete()
