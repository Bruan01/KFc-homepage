# pyright: reportMissingImports=false
"""Notification API views."""
from __future__ import annotations

from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User
from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_user
from apps.core.responses import json_error, json_ok

from .models import Notification
from .services import CATEGORIES, category_counts, message_unread_counts, payload, unread_count


@require_user
def notifications(request):
    if request.method == "GET":
        flt = request.GET.get("filter", "all")
        category = request.GET.get("category", "")
        try:
            limit = min(50, max(1, int(request.GET.get("limit", 30))))
        except ValueError:
            limit = 30
        qs = Notification.objects.filter(recipient=request.user)
        if category in CATEGORIES:
            qs = qs.filter(type__in=CATEGORIES[category])
        if flt == "unread":
            qs = qs.filter(is_read=False)
        # 读多几行再合并：同一发送人的私信通知只占一个位置，不能把别人的通知挤出面板。
        rows = list(qs[: min(limit * 4, 200)])
        names = {row.actor_username for row in rows if row.actor_username}
        actors = {
            user.username: {
                "username": user.username,
                "display_name": user.display_name or user.username,
                "avatar_url": user.avatar_url or "",
            }
            for user in User.objects.filter(username__in=names)
        } if names else {}
        items, conversations = [], {}
        for row in rows:
            if row.type == "message" and row.actor_username:
                item = conversations.get(row.actor_username)
                if item is None:
                    item = payload(row, actors)
                    item["ids"] = []
                    item["isRead"] = True
                    conversations[row.actor_username] = item
                    items.append(item)
                item["ids"].append(row.pk)
                item["isRead"] = item["isRead"] and bool(row.is_read)
                continue
            items.append(payload(row, actors))
        items = items[:limit]
        counts = message_unread_counts(request.user, conversations)
        for username, item in conversations.items():
            count = counts.get(username, 0)
            if count:
                item["body"] = f"你有 {count} 条新私信"
                item["isRead"] = False
        return json_ok({
            "items": items,
            "unreadCount": unread_count(request.user),
            "categories": category_counts(request.user),
        })
    from django.http import HttpResponseNotAllowed

    return HttpResponseNotAllowed(["GET"])


@require_user
@require_GET
def unread_count_view(request):
    return json_ok({"unreadCount": unread_count(request.user), "categories": category_counts(request.user)})


@require_user
@require_POST
def mark_read(request):
    try:
        body = read_json(request)
        ids = [int(i) for i in (body.get("ids") or []) if str(i).strip().lstrip("-").isdigit()]
    except (InvalidJSON, TypeError, ValueError):
        return json_error("invalid json")
    if ids:
        targets = Notification.objects.filter(recipient=request.user, id__in=ids)
        # 合并后的私信通知只暴露最新一行的 id，读取时要把同一发送人的整组都清掉。
        senders = {row.actor_username for row in targets if row.type == "message" and row.actor_username}
        targets.update(is_read=True)
        if senders:
            Notification.objects.filter(recipient=request.user, type="message", actor_username__in=senders).update(is_read=True)
    return json_ok({"ok": True, "unreadCount": unread_count(request.user)})


@require_user
@require_POST
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return json_ok({"ok": True, "unreadCount": 0})
