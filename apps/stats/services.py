"""Visit counting: in-memory buffer, batch flush, read helpers.

计数只发生在中间件里，真正落库走 ``maybe_flush`` 的时间/条数阈值；
进程退出时由 ``atexit`` 强制 flush，最坏情况只丢最后几秒的数据。
"""
from __future__ import annotations

import atexit
import collections
import hashlib
import logging
import threading
import time
from datetime import date, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

from . import taxonomy
from .models import VisitDaily, VisitPageDaily, VisitReferrerDaily, VisitVisitor

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 10.0
FLUSH_THRESHOLD = 300
MAX_PENDING_COUNTS = 5000

_LOCK = threading.Lock()
_PENDING: dict[str, dict] = {}
_LAST_FLUSH = 0.0


def _empty_bucket() -> dict:
    return {"pv": 0, "pages": collections.Counter(), "sources": collections.Counter(), "visitors": set()}


def fingerprint(day: str, ip: str, user_agent: str) -> str:
    """当天不可逆的访客标识：换一天就换一把盐，无法跨日追踪同一个人。"""
    raw = f"{settings.SECRET_KEY}|{day}|{ip}|{user_agent}"
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:24]


def record(*, path: str, referer: str, ip: str, user_agent: str, host: str) -> None:
    day = timezone.localdate().isoformat()
    page_key = taxonomy.classify_page(path)
    source_key = taxonomy.classify_referrer(referer, host)
    visitor = fingerprint(day, ip, user_agent)
    with _LOCK:
        bucket = _PENDING.get(day)
        if bucket is None:
            bucket = _PENDING[day] = _empty_bucket()
        bucket["pv"] += 1
        bucket["pages"][page_key] += 1
        bucket["sources"][source_key] += 1
        bucket["visitors"].add(visitor)


def maybe_flush() -> None:
    now = time.monotonic()
    with _LOCK:
        if not _PENDING:
            return
        pending = sum(bucket["pv"] for bucket in _PENDING.values())
        if now - _LAST_FLUSH < FLUSH_INTERVAL_SECONDS and pending < FLUSH_THRESHOLD:
            return
    flush()


def flush() -> None:
    global _LAST_FLUSH, _PENDING
    with _LOCK:
        batch = _PENDING
        _PENDING = {}
        _LAST_FLUSH = time.monotonic()
    if not batch:
        return
    try:
        _write(batch)
    except Exception:
        logger.exception("visit stats flush failed, re-queued %s day(s)", len(batch))
        with _LOCK:
            for day, bucket in batch.items():
                target = _PENDING.setdefault(day, _empty_bucket())
                target["pv"] += bucket["pv"]
                target["pages"].update(bucket["pages"])
                target["sources"].update(bucket["sources"])
                target["visitors"].update(bucket["visitors"])
                if sum(item["pv"] for item in _PENDING.values()) > MAX_PENDING_COUNTS:
                    _PENDING.clear()
                    break


def _write(batch: dict[str, dict]) -> None:
    daily_table = VisitDaily._meta.db_table
    page_table = VisitPageDaily._meta.db_table
    source_table = VisitReferrerDaily._meta.db_table
    with transaction.atomic():
        for day, bucket in batch.items():
            if not bucket["pv"]:
                continue
            with connection.cursor() as cursor:
                cursor.execute(
                    f'INSERT INTO "{daily_table}" (date, pv, uv) VALUES (%s, %s, 0) '
                    f'ON CONFLICT(date) DO UPDATE SET pv = "{daily_table}".pv + excluded.pv',
                    [day, bucket["pv"]],
                )
                for page_key, pv in bucket["pages"].items():
                    cursor.execute(
                        f'INSERT INTO "{page_table}" (date, page_key, pv) VALUES (%s, %s, %s) '
                        f'ON CONFLICT(date, page_key) DO UPDATE SET pv = "{page_table}".pv + excluded.pv',
                        [day, page_key, pv],
                    )
                for source_key, pv in bucket["sources"].items():
                    cursor.execute(
                        f'INSERT INTO "{source_table}" (date, source_key, pv) VALUES (%s, %s, %s) '
                        f'ON CONFLICT(date, source_key) DO UPDATE SET pv = "{source_table}".pv + excluded.pv',
                        [day, source_key, pv],
                    )
            if bucket["visitors"]:
                VisitVisitor.objects.bulk_create(
                    [VisitVisitor(date=day, fingerprint=item) for item in bucket["visitors"]],
                    ignore_conflicts=True,
                )
            uv = VisitVisitor.objects.filter(date=day).count()
            VisitDaily.objects.filter(date=day).update(uv=uv)


RANGE_LABELS = {"today": "今天", "7d": "近 7 天", "30d": "近 30 天", "all": "全部"}
RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30}
WEEK_BUCKET_DAYS = 7
DAILY_TREND_LIMIT = 31


def normalize_range(range_key=None, days=None) -> str:
    """``range`` 优先；旧客户端只传 ``days`` 时映射到最接近的范围。"""
    key = (range_key or "").strip().lower()
    if key in RANGE_LABELS:
        return key
    try:
        value = int(days)
    except (TypeError, ValueError):
        return "7d"
    if value <= 1:
        return "today"
    if value <= 7:
        return "7d"
    if value <= 30:
        return "30d"
    return "all"


def _range_start(range_key: str, today: date) -> date:
    if range_key != "all":
        return today - timedelta(days=RANGE_DAYS[range_key] - 1)
    earliest = VisitDaily.objects.order_by("date").values_list("date", flat=True).first()
    if not earliest:
        return today
    try:
        start = date.fromisoformat(earliest)
    except ValueError:
        return today
    return min(start, today)


def _bucket_label(start, end) -> str:
    if start == end:
        return f"{start.month}/{start.day}"
    if start.month == end.month:
        return f"{start.month}/{start.day}-{end.day}"
    return f"{start.month}/{start.day}-{end.month}/{end.day}"


def _daily_trend(start, today, daily) -> list[dict]:
    trend = []
    day = start
    while day <= today:
        key = day.isoformat()
        row = daily.get(key)
        trend.append({
            "date": key,
            "label": _bucket_label(day, day),
            "pv": row.pv if row else 0,
            "uv": row.uv if row else 0,
        })
        day += timedelta(days=1)
    return trend


def _weekly_trend(start, today, daily) -> list[dict]:
    trend = []
    cursor = start
    while cursor <= today:
        end = min(cursor + timedelta(days=WEEK_BUCKET_DAYS - 1), today)
        pv = 0
        day = cursor
        while day <= end:
            row = daily.get(day.isoformat())
            if row:
                pv += row.pv
            day += timedelta(days=1)
        uv = (
            VisitVisitor.objects.filter(date__gte=cursor.isoformat(), date__lte=end.isoformat())
            .values("fingerprint")
            .distinct()
            .count()
        )
        trend.append({
            "date": cursor.isoformat(),
            "end_date": end.isoformat(),
            "label": _bucket_label(cursor, end),
            "pv": pv,
            "uv": uv,
        })
        cursor = end + timedelta(days=1)
    return trend


def summary(range_key: str | None = None, days: int | None = None) -> dict:
    """后台大屏用的聚合视图；查询前先落库，保证数字是当前时刻的。"""
    flush()
    key = normalize_range(range_key, days)
    today = timezone.localdate()
    today_s = today.isoformat()
    start = _range_start(key, today)
    start_s = start.isoformat()
    span_days = (today - start).days + 1

    daily = {row.date: row for row in VisitDaily.objects.filter(date__gte=start_s)}
    total_pv = sum(row.pv for row in daily.values())
    total_uv = (
        VisitVisitor.objects.filter(date__gte=start_s)
        .values("fingerprint")
        .distinct()
        .count()
    )

    weekly = span_days > DAILY_TREND_LIMIT
    trend = _weekly_trend(start, today, daily) if weekly else _daily_trend(start, today, daily)
    today_row = daily.get(today_s)

    page_totals = (
        VisitPageDaily.objects.filter(date__gte=start_s)
        .values("page_key")
        .annotate(pv=Sum("pv"))
        .order_by("-pv")[:8]
    )
    top_pages = [
        {
            "key": item["page_key"],
            "label": taxonomy.page_label(item["page_key"]),
            "path": taxonomy.page_path(item["page_key"]),
            "pv": int(item["pv"] or 0),
            "share": _share(item["pv"], total_pv),
        }
        for item in page_totals
    ]

    source_totals = (
        VisitReferrerDaily.objects.filter(date__gte=start_s)
        .values("source_key")
        .annotate(pv=Sum("pv"))
        .order_by("-pv")[:8]
    )
    sources = [
        {
            "key": item["source_key"],
            "label": taxonomy.source_label(item["source_key"]),
            "pv": int(item["pv"] or 0),
            "share": _share(item["pv"], total_pv),
        }
        for item in source_totals
    ]

    avg_pv = round(total_pv / span_days, 1) if span_days else 0.0
    return {
        "range": key,
        "range_label": RANGE_LABELS[key],
        "start_date": start_s,
        "days": span_days,
        "bucket": "week" if weekly else "day",
        "updated_at": timezone.now().isoformat(),
        "today": {
            "date": today_s,
            "label": f"{today.month}/{today.day}",
            "pv": today_row.pv if today_row else 0,
            "uv": today_row.uv if today_row else 0,
        },
        "totals": {"pv": total_pv, "uv": total_uv, "avg_pv": avg_pv},
        "trend": trend,
        "top_pages": top_pages,
        "sources": sources,
    }


def _share(value, total) -> float:
    try:
        total = int(total or 0)
        if total <= 0:
            return 0.0
        return round(int(value or 0) * 100 / total, 1)
    except (TypeError, ValueError):
        return 0.0


def cleanup(keep_days: int = 90) -> dict[str, int]:
    cutoff = (timezone.localdate() - timedelta(days=max(1, int(keep_days)))).isoformat()
    deleted: dict[str, int] = {}
    for model in (VisitPageDaily, VisitReferrerDaily, VisitVisitor, VisitDaily):
        deleted[model._meta.db_table] = model.objects.filter(date__lt=cutoff).delete()[0]
    return deleted


def reset() -> None:
    """测试用：清空内存缓冲，避免用例之间互相污染。"""
    global _LAST_FLUSH
    with _LOCK:
        _PENDING.clear()
        _LAST_FLUSH = 0.0


_EXIT_HOOK_REGISTERED = False


def register_exit_flush() -> None:
    """进程正常退出前把缓冲落库一次；解释器关闭阶段的异常一律吞掉。"""
    global _EXIT_HOOK_REGISTERED
    if _EXIT_HOOK_REGISTERED:
        return
    _EXIT_HOOK_REGISTERED = True
    atexit.register(_flush_at_exit)


def _flush_at_exit() -> None:
    try:
        flush()
    except Exception:
        pass
