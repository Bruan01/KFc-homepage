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
        if not str(title or "").strip():
            title = DEFAULT_TITLES.get(type_, "系统通知")
        Notification.objects.create(
            recipient=recipient,
            type=type_ if type_ in DEFAULT_TITLES else "system",
            title=str(title)[:200],
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


DEFAULT_TITLES = {
    "badge": "获得新勋章",
    "level": "等级提升",
    "like": "作品收到点赞",
    "reply": "作品收到评论",
    "reply_like": "评论收到点赞",
    "mention": "有人在回复中提到了你",
    "sale": "商品售出",
    "system": "系统通知",
}


def payload(row: Notification) -> dict:
    type_ = row.type if row.type in DEFAULT_TITLES else "system"
    return {
        "id": row.pk,
        "type": type_,
        "title": row.title or DEFAULT_TITLES[type_],
        "body": row.body or "",
        "link": row.link or "",
        "isRead": bool(row.is_read),
        "createdAt": timezone.localtime(row.created_at).isoformat() if row.created_at else "",
    }
