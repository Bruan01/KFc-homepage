# pyright: reportMissingImports=false
"""Payload helpers for the Vibecoding electronic book."""
from __future__ import annotations

from collections.abc import Iterable

from .constants import (
    BOOK_DESCRIPTION,
    BOOK_EDITION,
    BOOK_PAGE_SEPARATOR,
    BOOK_PARTS,
    BOOK_SUBTITLE,
    BOOK_TITLE,
)


def split_book_pages(content_md: str) -> list[str]:
    """Split authored Markdown at explicit page boundaries, omitting empty pages."""
    pages = [page.strip() for page in str(content_md or "").split(BOOK_PAGE_SEPARATOR)]
    return [page for page in pages if page] or [""]


def part_number_for_series(series: str) -> int | None:
    """Return the configured volume number for a tutorial series."""
    for part in BOOK_PARTS:
        if part["title"] == series:
            return int(part["number"])
    return None


def tutorial_summary_payload(tutorial) -> dict:
    """Serialize one tutorial for the table of contents."""
    return {
        "id": tutorial.pk,
        "slug": tutorial.slug,
        "title": tutorial.title,
        "summary": tutorial.summary,
        "difficulty": tutorial.difficulty,
        "kind": tutorial.kind,
        "series": tutorial.series,
        "part_number": part_number_for_series(tutorial.series),
        "chapter_number": tutorial.sort_order,
        "cover_url": tutorial.cover_url,
        "tags": tutorial.tag_list,
        "reading_minutes": tutorial.reading_minutes,
        "page_count": len(split_book_pages(tutorial.content_md)),
        "views": tutorial.views,
        "updated_at": tutorial.updated_at.isoformat(),
    }


def book_payload(tutorials: Iterable) -> dict:
    """Build book metadata and a five-volume table of contents."""
    rows = list(tutorials)
    summaries = [tutorial_summary_payload(tutorial) for tutorial in rows]
    parts = []
    for part in BOOK_PARTS:
        chapters = [item for item in summaries if item["series"] == part["title"]]
        parts.append({**part, "chapters": chapters})
    return {
        "title": BOOK_TITLE,
        "subtitle": BOOK_SUBTITLE,
        "edition": BOOK_EDITION,
        "description": BOOK_DESCRIPTION,
        "chapter_count": len(summaries),
        "page_count": sum(item["page_count"] for item in summaries),
        "reading_minutes": sum(item["reading_minutes"] for item in summaries),
        "parts": parts,
    }
