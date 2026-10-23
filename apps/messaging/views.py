import re
from datetime import timedelta
from urllib.parse import quote
from django.db import transaction
from django.db.models import Q, Exists, OuterRef, Subquery, Count
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from apps.accounts.models import User
from apps.core.http import read_json, InvalidJSON
from apps.core.permissions import require_user
from apps.core.responses import json_ok, json_error
from apps.murmurs.models import MurmurBlock
from apps.notifications.models import Notification
from apps.notifications.services import notify
from .models import PrivateMessage


def private(response):
    response["Cache-Control"] = "no-store"
    return response


def identity(user):
    return {"username": user.username, "display_name": user.display_name or user.username, "avatar_url": user.avatar_url}


def blocked(a, b):
    return MurmurBlock.objects.filter(Q(username=a, blocked_username=b) | Q(username=b, blocked_username=a)).exists()


def pair(user, peer):
    return PrivateMessage.objects.filter(Q(sender=user, recipient=peer) | Q(sender=peer, recipient=user))


@require_GET
@require_user
def inbox(request):
    me = request.user
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return json_error("分页参数错误")
    latest = PrivateMessage.objects.filter(Q(sender=me, recipient=OuterRef("pk")) | Q(recipient=me, sender=OuterRef("pk"))).order_by("-id")
    unread = PrivateMessage.objects.filter(sender=OuterRef("pk"), recipient=me, is_read=False).order_by().values("sender").annotate(n=Count("id")).values("n")
    qs = User.objects.annotate(has_chat=Exists(latest), last_id=Subquery(latest.values("id")[:1]),
                               last_content=Subquery(latest.values("content")[:1]), unread=Coalesce(Subquery(unread), 0))
    qs = qs.filter(has_chat=True).exclude(pk=me.pk).order_by("-last_id")
    total = qs.count()
    return private(json_ok({"items": [{**identity(user), "preview": user.last_content[:100], "unread": user.unread}
                                      for user in qs[(page-1)*20:page*20]], "page": page, "total": total,
                            "unread": PrivateMessage.objects.filter(recipient=me, is_read=False).count()}))


@require_http_methods(["GET", "POST"])
@require_user
def thread(request, username):
    peer = User.objects.filter(username=username, is_system_generated=False).first()
    if not peer:
        return json_error("用户不存在或暂不支持私信", status=404)
    if peer.pk == request.user.pk:
        return json_error("不能给自己发送私信")
    if request.method == "GET":
        qs = pair(request.user, peer)
        try:
            before = int(request.GET.get("before", 0))
            after = int(request.GET.get("after", 0))
            if before < 0 or after < 0 or (before and after):
                raise ValueError
        except ValueError:
            return json_error("分页参数错误")
        if before:
            qs = qs.filter(pk__lt=before)
        if after:
            qs = qs.filter(pk__gt=after)
        rows = list(qs.order_by("id" if after else "-id")[:31])
        more = len(rows) > 30
        rows = rows[:30]
        if not after:
            rows.reverse()
        return private(json_ok({"peer": identity(peer), "blocked": blocked(request.user.username, username),
                                "items": [{"id": row.pk, "content": row.content, "mine": row.sender_id == request.user.pk,
                                           "created_at": row.created_at.isoformat(), "is_read": row.is_read} for row in rows],
                                "next_cursor": rows[0].pk if rows and more and not after else None, "has_more": more}))
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("消息格式错误")
    content, key = body.get("content", ""), body.get("client_key", "")
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 2000:
        return json_error("私信须为 1–2000 字")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", key):
        return json_error("消息标识错误，请刷新后重试")
    with transaction.atomic():
        # Serialise sends per account so concurrent clients cannot bypass limits.
        User.objects.select_for_update().get(pk=request.user.pk)
        if blocked(request.user.username, username):
            return json_error("双方存在屏蔽关系，暂时无法发送私信", status=403)
        old = PrivateMessage.objects.filter(sender=request.user, client_key=key).first()
        if old:
            if old.recipient_id != peer.pk or old.content != content.strip():
                return json_error("该消息已处理，请重新发送", status=409)
            return private(json_ok({"id": old.pk, "replayed": True}))
        if PrivateMessage.objects.filter(sender=request.user, created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= 15:
            return json_error("发送过于频繁，请稍后再试", status=429)
        row = PrivateMessage.objects.create(sender=request.user, recipient=peer, content=content.strip(), client_key=key)
        notify(recipient=peer, type_="message", title=f"{request.user.display_name or request.user.username} 给你发来私信",
               body="你有一条新私信", link=f"/messages?user={quote(request.user.username, safe='')}", actor_username=request.user.username)
    return private(json_ok({"id": row.pk}, status=201))


@require_POST
@require_user
def mark_read(request, username):
    try:
        upto = read_json(request).get("upto")
    except InvalidJSON:
        return json_error("请求格式错误")
    if type(upto) is not int or upto < 1:
        return json_error("消息标识错误")
    with transaction.atomic():
        PrivateMessage.objects.filter(recipient=request.user, sender__username=username, pk__lte=upto).update(is_read=True)
        if not PrivateMessage.objects.filter(recipient=request.user, sender__username=username, is_read=False).exists():
            Notification.objects.filter(recipient=request.user, actor_username=username, type="message", is_read=False).update(is_read=True)
    return private(json_ok({"read": True}))
