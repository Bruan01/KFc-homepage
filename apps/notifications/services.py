# pyright: reportMissingImports=false
"""Notification services: create + query helpers. Never raises into caller flows."""
from __future__ import annotations

from django.utils import timezone

from .models import Notification


def notify(*, recipient, type_: str, title: str, body: str = "", link: str = "", actor_username: str = "") -> None:
    """Create a notification; skip self-notifications and swallow all errors."""
    try:
        if recipient is None:
            return
        if actor_username and getattr(recipient, "username", "") == actor_username:
            return
        Notification.objects.create(
            recipient=recipient,
            type=type_,
            title=title[:200],
            body=(body or "")[:300],
            link=(link or "")[:300],
            actor_username=actor_username or "",
        )
    except Exception:
        pass


def unread_count(user) -> int:
    try:
        return Notification.objects.filter(recipient=user, is_read=False).count()
    except Exception:
        return 0


def payload(row: Notification) -> dict:
    return {
        "id": row.pk,
        "type": row.type,
        "title": row.title,
        "body": row.body,
        "link": row.link,
        "isRead": row.is_read,
        "createdAt": timezone.localtime(row.created_at).isoformat() if row.created_at else "",
    }
