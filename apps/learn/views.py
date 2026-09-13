# pyright: reportMissingImports=false
"""Learn API views: glossary and tutorials."""
from __future__ import annotations

from django.db.models import F
from django.views.decorators.http import require_GET, require_POST

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_user
from apps.core.responses import json_error, json_ok

from .models import GlossaryTerm, LearnProgress, Tutorial


@require_GET
def glossary(request):
    category = request.GET.get("category", "").strip()
    qs = GlossaryTerm.objects.filter(is_active=True)
    if category:
        qs = qs.filter(category=category)
    items = [
        {
            "id": term.pk,
            "slug": term.slug,
            "term": term.term,
            "en": term.en,
            "definition": term.definition,
            "category": term.category,
            "hasDetail": bool(term.content_md),
        }
        for term in qs
    ]
    categories = list(
        GlossaryTerm.objects.filter(is_active=True)
        .order_by()
        .values_list("category", flat=True)
        .distinct()
    )
    return json_ok({"items": items, "categories": categories})


@require_GET
def glossary_detail(request, slug: str):
    term = GlossaryTerm.objects.filter(slug=slug, is_active=True).first()
    if not term:
        return json_error("词条不存在", status=404)
    related = [
        {"slug": row.slug, "term": row.term, "en": row.en}
        for row in GlossaryTerm.objects.filter(category=term.category, is_active=True).exclude(pk=term.pk).order_by("sort_order")[:6]
    ]
    return json_ok({
        "term": {
            "id": term.pk,
            "slug": term.slug,
            "term": term.term,
            "en": term.en,
            "definition": term.definition,
            "contentMd": term.content_md or term.definition,
            "category": term.category,
            "related": related,
        }
    })


@require_GET
def tutorials(request):
    kind = request.GET.get("kind", "").strip()
    difficulty = request.GET.get("difficulty", "").strip()
    qs = Tutorial.objects.filter(status=Tutorial.STATUS_PUBLISHED)
    if kind in {"tutorial", "paradigm"}:
        qs = qs.filter(kind=kind)
    if difficulty in {Tutorial.DIFFICULTY_BEGINNER, Tutorial.DIFFICULTY_INTERMEDIATE}:
        qs = qs.filter(difficulty=difficulty)
    items = [
        {
            "id": tutorial.pk,
            "slug": tutorial.slug,
            "title": tutorial.title,
            "summary": tutorial.summary,
            "difficulty": tutorial.difficulty,
            "kind": tutorial.kind,
            "series": tutorial.series,
            "cover_url": tutorial.cover_url,
            "tags": tutorial.tag_list,
            "reading_minutes": tutorial.reading_minutes,
            "views": tutorial.views,
            "updated_at": tutorial.updated_at.isoformat(),
        }
        for tutorial in qs
    ]
    return json_ok({"items": items})


@require_GET
def tutorial_detail(request, slug: str):
    tutorial = Tutorial.objects.filter(slug=slug, status=Tutorial.STATUS_PUBLISHED).first()
    if not tutorial:
        return json_error("教程不存在", status=404)
    Tutorial.objects.filter(pk=tutorial.pk).update(views=F("views") + 1)
    series_items = []
    if tutorial.series:
        series_items = [
            {"slug": row.slug, "title": row.title}
            for row in Tutorial.objects.filter(series=tutorial.series, status=Tutorial.STATUS_PUBLISHED).order_by("sort_order", "id")
        ]
    return json_ok({
        "tutorial": {
            "id": tutorial.pk,
            "slug": tutorial.slug,
            "title": tutorial.title,
            "summary": tutorial.summary,
            "content_md": tutorial.content_md,
            "difficulty": tutorial.difficulty,
            "kind": tutorial.kind,
            "series": tutorial.series,
            "cover_url": tutorial.cover_url,
            "tags": tutorial.tag_list,
            "reading_minutes": tutorial.reading_minutes,
            "views": tutorial.views + 1,
            "series_items": series_items,
            "updated_at": tutorial.updated_at.isoformat(),
        }
    })


@require_user
@require_POST
def complete(request):
    """标记一篇教程/词条学习完成；幂等；返回新获得的勋章。"""
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("invalid json")
    kind = str(body.get("kind", "")).strip()
    slug = str(body.get("slug", "")).strip()
    if kind not in {LearnProgress.KIND_TUTORIAL, LearnProgress.KIND_TERM}:
        return json_error("kind 必须是 tutorial 或 term")
    if not slug or len(slug) > 140:
        return json_error("slug 无效")
    _, created = LearnProgress.objects.get_or_create(user=request.user, kind=kind, slug=slug)
    new_badges = []
    try:
        from apps.gamification.services import check_user_achievements

        new_badges = [
            {"name": b.name, "icon": b.icon, "tier": b.tier}
            for b in check_user_achievements(request.user)
        ]
    except Exception:
        new_badges = []
    from apps.learn.models import LearnProgress as LP

    done = LP.objects.filter(user=request.user, kind=kind).count()
    return json_ok({"ok": True, "created": created, "newBadges": new_badges, "completed": done})
