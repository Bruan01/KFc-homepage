"""Date-based ten-item pages and per-user unread reply tracking."""
from datetime import date, datetime, time, timedelta
from django.db import transaction
from django.db.models import Exists, OuterRef, Subquery, Value, DateTimeField
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.core.http import read_json, InvalidJSON
from apps.core.responses import json_ok, json_error
from .models import MurmurComment, MurmurReadState, MurmurBlock
from .services import actor, visible_posts, serialize_posts


def page_feed(request, qs, username):
    unread = request.GET.get("unread") == "1"
    if unread and not username:
        return json_error("登录后才能筛选新回复", status=401)
    base_qs = qs
    try:
        page = int(request.GET.get("page", 1))
        if page < 1 or page > 100000:
            raise ValueError
        today = timezone.localdate().isoformat()
        start_raw, end_raw = request.GET.get("start", ""), request.GET.get("end", "")
        # 前端默认只翻「今天」；显式指定历史区间时是用户在查档案，
        # 置顶不能跨窗口插进来（见 keeps_pins_within_range 契约）。
        default_today = False
        if not unread and not start_raw and not end_raw:
            start_raw = end_raw = today
            default_today = True
        if bool(start_raw) != bool(end_raw):
            raise ValueError
        if start_raw:
            start, end = date.fromisoformat(start_raw), date.fromisoformat(end_raw)
            if start > end:
                raise ValueError
            lower = timezone.make_aware(datetime.combine(start, time.min))
            upper = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
            qs = qs.annotate(created_time=Cast("created_at", DateTimeField())).filter(created_time__gte=lower, created_time__lt=upper)
    except (ValueError, OverflowError):
        return json_error("请选择有效的起止日期和页码")
    if unread:
        read = MurmurReadState.objects.filter(murmur_id=OuterRef("murmur_id"), username=username).values("last_comment_id")[:1]
        unseen = MurmurComment.objects.filter(murmur_id=OuterRef("pk"), is_deleted=False).exclude(author_username=username)
        blocked = MurmurBlock.objects.filter(username=username).values("blocked_username")
        unseen = unseen.exclude(author_username__in=blocked).annotate(last_read=Coalesce(Subquery(read), Value(0))).filter(pk__gt=Coalesce(Subquery(read), Value(0)))
        participated = MurmurComment.objects.filter(murmur_id=OuterRef("pk"), author_username=username, is_deleted=False)
        from django.db.models import Q
        qs = qs.annotate(has_unread=Exists(unseen), participated=Exists(participated)).filter(
            Q(author_username=username) | Q(participated=True), has_unread=True)
    total = qs.count()
    pages = max(1, (total + 9) // 10)
    page = min(page, pages)
    rows = list(qs.order_by("-is_pinned", "-id")[(page-1)*10:page*10])
    # 置顶是公告，优先级高于任何时间筛选：第一页把窗口外的置顶帖浮到最前。
    # 「未读」是个人视图，不掺置顶；窗口内已有的置顶由 -is_pinned 排序负责。
    # total/total_pages 只描述窗口内的量，否则补进来的置顶会让第二页误报还有内容。
    if not unread and page == 1:
        inside = list(qs.filter(is_pinned=True).values_list("pk", flat=True))
        extra = list(base_qs.filter(is_pinned=True).exclude(pk__in=inside).order_by("-id"))
        if extra:
            # 合并后按「置顶新到旧 → 普通新到旧」重排，并压回 10 条：
            # 直接前插会让 items 变 11 条，第二页还可能重复同一条置顶。
            rows = sorted(extra + rows, key=lambda row: (row.is_pinned, row.pk), reverse=True)[:10]
    response = json_ok({"items": serialize_posts(rows, username), "page": page, "page_size": 10,
                        "total": total, "total_pages": pages, "start": start_raw, "end": end_raw, "next_cursor": None})
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def mark_read(request, post_id):
    username = actor(request)
    if not username:
        return json_error("请先登录", status=401)
    post = visible_posts(username).filter(pk=post_id).first()
    if not post:
        return json_error("碎碎念不可见", status=404)
    try:
        upto = read_json(request).get("upto")
    except InvalidJSON:
        return json_error("请求格式错误")
    if type(upto) is not int or upto < 0:
        return json_error("评论标识错误")
    if upto and not post.comments.filter(pk=upto, is_deleted=False).exists():
        return json_error("评论不存在", status=404)
    with transaction.atomic():
        row, _ = MurmurReadState.objects.get_or_create(murmur=post, username=username)
        MurmurReadState.objects.filter(pk=row.pk, last_comment_id__lt=upto).update(last_comment_id=upto)
    return json_ok({"read": True})
