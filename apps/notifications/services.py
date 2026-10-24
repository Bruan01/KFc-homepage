# pyright: reportMissingImports=false
"""Notification services: create + query helpers. Never raises into caller flows."""
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone

from .models import Notification

# 消息中心左侧分类 → 通知类型。私信单独走 messaging 的未读计数。
CATEGORIES = {
    "reply": ("reply",),
    "mention": ("mention",),
    "like": ("like", "reply_like"),
    "system": ("system", "badge", "level", "sale"),
}


def category_counts(user) -> dict:
    try:
        rows = (Notification.objects.filter(recipient=user, is_read=False)
                .values("type").annotate(n=Count("id")))
        by_type = {row["type"]: row["n"] for row in rows}
    except Exception:
        by_type = {}
    return {name: sum(by_type.get(type_, 0) for type_ in types) for name, types in CATEGORIES.items()}


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


def notify_message(*, recipient, sender, count: int, link: str = "") -> None:
    """One notification per sender: later messages refresh the same unread row."""
    try:
        if recipient is None or getattr(recipient, "pk", None) == getattr(sender, "pk", None):
            return
        name = sender.display_name or sender.username
        row = (Notification.objects
               .filter(recipient=recipient, type="message", actor_username=sender.username, is_read=False)
               .order_by("-id").first())
        if row:
            row.title = f"{name} 给你发来私信"[:200]
            row.body = f"你有 {count} 条新私信"[:300]
            row.link = (link or "")[:300]
            row.created_at = timezone.now()
            row.save(update_fields=["title", "body", "link", "created_at"])
            # 之前逐条私信留下的未读副本并进这一条，铃铛数字才不会虚高。
            (Notification.objects
             .filter(recipient=recipient, type="message", actor_username=sender.username, is_read=False)
             .exclude(pk=row.pk).update(is_read=True))
            return
        Notification.objects.create(
            recipient=recipient,
            type="message",
            title=f"{name} 给你发来私信"[:200],
            body=f"你有 {count} 条新私信"[:300],
            link=(link or "")[:300],
            actor_username=sender.username,
        )
    except Exception:
        pass


def message_unread_counts(user, usernames) -> dict:
    """每个发送人当前还有几条未读私信。"""
    from apps.messaging.models import PrivateMessage

    usernames = [name for name in usernames if name]
    if not usernames:
        return {}
    rows = (PrivateMessage.objects
            .filter(recipient=user, sender__username__in=usernames, is_read=False)
            .values("sender__username").annotate(n=Count("id")))
    return {row["sender__username"]: row["n"] for row in rows}


def unread_count(user) -> int:
    try:
        qs = Notification.objects.filter(recipient=user, is_read=False)
        # 私信按发送人算一条，历史遗留的逐条通知不能重复计数。
        senders = qs.filter(type="message").values("actor_username").distinct().count()
        return qs.exclude(type="message").count() + senders
    except Exception:
        return 0


DEFAULT_TITLES = {
    "badge": "获得新勋章",
    "level": "等级提升",
    "like": "作品收到点赞",
    "reply": "作品收到评论",
    "reply_like": "评论收到点赞",
    "mention": "有人在回复中提到了你",
    "message": "私信",
    "sale": "商品售出",
    "system": "系统通知",
}


def payload(row: Notification, actors: dict | None = None) -> dict:
    type_ = row.type if row.type in DEFAULT_TITLES else "system"
    actor = (actors or {}).get(row.actor_username) if row.actor_username else None
    return {
        "id": row.pk,
        "type": type_,
        "title": row.title or DEFAULT_TITLES[type_],
        "body": row.body or "",
        "link": row.link or "",
        "isRead": bool(row.is_read),
        "actor": actor or {},
        "createdAt": timezone.localtime(row.created_at).isoformat() if row.created_at else "",
    }
