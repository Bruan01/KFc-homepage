from __future__ import annotations

import os
import time
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.db import connection
from django.db.models import Count
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.models import AdminAccount, User
from apps.core.permissions import require_admin
from apps.core.responses import json_ok
from apps.downloads.models import Download, DownloadRequest
from apps.catalog.models import Product
from apps.forum.models import ForumTopic
from apps.imaging.models import ImageGenerationJob
from apps.murmurs.models import Murmur
from apps.points.models import UserDailyActivity
from apps.publishing.models import ProductDeleteRequest, PublishRequest
from apps.stats.models import VisitVisitor
from apps.stats.services import RANGE_DAYS, RANGE_LABELS, normalize_range

TABLES=["products","product_packages","product_versions","downloads","download_requests","publish_requests","publish_request_votes","product_delete_requests","users","point_accounts","point_ledger","user_daily_activity","download_entitlements","email_verification_codes","subscribers","user_subscriptions","admin_accounts","admin_upload_events","system_settings"]
MASKED={"password","password_hash","code_hash","token"}
STARTED_AT=time.time()


def mask(name,value):
    if name not in MASKED:return value.hex() if isinstance(value,bytes) else value
    text=str(value or "")
    return "" if not text else "*"*len(text) if len(text)<=8 else f"{text[:2]}***{text[-2:]}"


_SCHEMA_CACHE: dict[str, list] = {}


def _table_columns(cursor, table):
    """表结构在进程生命周期内几乎不变，缓存起来。

    Django 5.2 的 SQLite introspection 在 can_introspect_json_field 时会「逐列」发一条
    sqlite_master 查询（products 24 列 = 24 条）。19 张表合计 189 条查询，全花在
    重复读同一份表结构上，而它和管理员大屏的数据新鲜度毫无关系。
    """
    cached = _SCHEMA_CACHE.get(table)
    if cached is not None:
        return cached
    columns = connection.introspection.get_table_description(cursor, table)
    _SCHEMA_CACHE[table] = columns
    return columns


def snapshot(table):
    with connection.cursor() as cursor:
        columns=_table_columns(cursor,table);names=[x.name for x in columns]
        cursor.execute(f'SELECT COUNT(*) FROM "{table}"');count=cursor.fetchone()[0]
        order="id" if "id" in names else "updated_at" if "updated_at" in names else names[0]
        cursor.execute(f'SELECT * FROM "{table}" ORDER BY "{order}" DESC LIMIT 10');rows=[{name:mask(name,value) for name,value in zip(names,row)} for row in cursor.fetchall()]
        breakdown=[]
        if "status" in names:
            cursor.execute(f'SELECT status,COUNT(*) FROM "{table}" GROUP BY status ORDER BY COUNT(*) DESC');breakdown=[{"status":x[0],"count":x[1]} for x in cursor.fetchall()]
    return {"name":table,"is_internal":False,"row_count":count,"columns":[{"name":x.name,"type":str(x.type_code),"not_null":not x.null_ok,"default":x.default,"primary_key_index":1 if x.name=="id" else 0} for x in columns],"status_breakdown":breakdown,"rows":rows,"limit":10,"offset":0,"has_more":count>10}


def _retention_pairs(start_date, today_s: str) -> tuple[int, int]:
    """区间内「活跃日 → 次日仍活跃」的人数配对。

    user_daily_activity 是 (user_id, activity_date) 明细，用 SQLite 的日期加法做
    自连接，避免把整段活跃明细拉进内存。
    """
    where = "a.activity_date < %s"
    params: list[str] = [today_s]
    if start_date:
        where += " AND a.activity_date >= %s"
        params.append(start_date.isoformat())
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM user_daily_activity a WHERE {where}", params)
        active_days = cursor.fetchone()[0]
        if not active_days:
            return 0, 0
        cursor.execute(
            f"""SELECT COUNT(*) FROM user_daily_activity a
                WHERE {where} AND EXISTS (
                    SELECT 1 FROM user_daily_activity b
                    WHERE b.user_id = a.user_id
                      AND b.activity_date = date(a.activity_date, '+1 day')
                )""",
            params,
        )
        retained = cursor.fetchone()[0]
    return retained, active_days


def _community_metrics(range_key: str) -> dict:
    local_now = timezone.localtime()
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = day_start.date()
    today_s = today.isoformat()
    if range_key == "all":
        start_date = None
        start_day = None
        start_iso = None
    else:
        start_date = today - timedelta(days=RANGE_DAYS[range_key] - 1)
        start_day = day_start - timedelta(days=RANGE_DAYS[range_key] - 1)
        # 历史文本时间戳是 UTC ISO-8601，按本地零点换算后做字符串比较
        start_iso = start_day.astimezone(dt_timezone.utc).isoformat()

    users = User.objects.all() if start_iso is None else User.objects.filter(created_at__gte=start_iso)
    users_new = users.count()
    activity = UserDailyActivity.objects.all()
    if start_date:
        activity = activity.filter(activity_date__gte=start_date.isoformat())
    active = activity.values("user_id").distinct().count()
    retained, active_days = _retention_pairs(start_date, today_s)

    topics = ForumTopic.objects.exclude(status=ForumTopic.STATUS_DELETED)
    murmurs = Murmur.objects.filter(is_deleted=False)
    jobs = ImageGenerationJob.objects.all()
    if start_day:
        topics = topics.filter(created_at__gte=start_day)
        murmurs = murmurs.filter(created_at__gte=start_iso)
        jobs = jobs.filter(created_at__gte=start_day)
    imaging_by_status = {
        row["status"]: row["count"]
        for row in jobs.values("status").annotate(count=Count("id"))
    }

    visitors = VisitVisitor.objects.all()
    if start_date:
        visitors = visitors.filter(date__gte=start_date.isoformat())
    uv = visitors.values("fingerprint").distinct().count()

    return {
        "range": range_key,
        "range_label": RANGE_LABELS[range_key],
        "date": today_s,
        "users_total": User.objects.count(),
        "users_new": users_new,
        "users_active": active,
        "retention_next_day": round(retained / active_days * 100, 1) if active_days else None,
        "retained_user_days": retained,
        "active_user_days": active_days,
        "topics": topics.count(),
        "murmurs": murmurs.count(),
        "imaging_completed": imaging_by_status.get("completed", 0),
        "imaging_failed": imaging_by_status.get("failed", 0),
        "uv": uv,
        "signup_conversion": round(users_new / uv * 100, 1) if uv else None,
    }


@require_admin()
@require_GET
def dashboard(request):
    range_key = normalize_range(request.GET.get("range"))
    existing=set(connection.introspection.table_names());tables=[snapshot(x) for x in TABLES if x in existing];total=sum(x["row_count"] for x in tables)
    active_sessions=__import__("django").contrib.sessions.models.Session.objects.filter(expire_date__gte=__import__("django").utils.timezone.now()).count()
    # metrics 里的这些数字 snapshot() 已经算过一遍（COUNT(*) 与 GROUP BY status），
    # 再从 ORM 查一次属于重复劳动 —— 每项都是一条独立 SQL。
    by_name = {item["name"]: item for item in tables}

    def _rows(name):
        return by_name.get(name, {}).get("row_count", 0)

    def _status(name, value):
        for item in by_name.get(name, {}).get("status_breakdown", []):
            if item.get("status") == value:
                return item.get("count", 0)
        return 0

    community = _community_metrics(range_key)

    return json_ok({
        "generated_at":__import__("django").utils.timezone.now().isoformat(),
        "viewer":{"username":request.kflow_admin["username"],"admin_level":request.kflow_admin["admin_level"],"is_super":request.kflow_admin["is_super"]},
        "service":{"status":"online","server_time":__import__("django").utils.timezone.now().isoformat(),"started_at":__import__("datetime").datetime.fromtimestamp(STARTED_AT,__import__("datetime").timezone.utc).isoformat(),"uptime_seconds":int(time.time()-STARTED_AT),"host":request.get_host().split(":")[0],"port":request.get_port(),"process_id":os.getpid(),"db_status":"online","db_path":str(settings.DATABASES["default"]["NAME"]),"session_ttl_seconds":settings.SESSION_COOKIE_AGE,"active_sessions":active_sessions,"admin_sessions":0,"user_sessions":active_sessions},
        "metrics":{
            "table_count":len(tables),
            "total_row_count":total,
            "products_total":_rows("products"),
            "products_published":_status("products","published"),
            "products_draft":_status("products","draft"),
            "downloads_total":_rows("downloads"),
            "users_total":_rows("users"),
            "subscribers_total":0,
            "admin_accounts_total":_rows("admin_accounts"),
            "pending_download_requests":_status("download_requests","pending"),
            "pending_publish_requests":_status("publish_requests","pending"),
            "pending_delete_requests":_status("product_delete_requests","pending"),
        },
        "community": community,
        "tables":tables,
    })


@require_admin()
@require_GET
def community(request):
    range_key = normalize_range(request.GET.get("range"))
    return json_ok({
        "generated_at": timezone.now().isoformat(),
        "community": _community_metrics(range_key),
    })
