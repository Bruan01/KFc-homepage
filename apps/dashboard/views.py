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
from apps.stats.models import VisitDaily

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


@require_admin()
@require_GET
def dashboard(request):
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

    local_now = timezone.localtime()
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = day_start.date().isoformat()
    yesterday = (day_start.date() - timedelta(days=1)).isoformat()
    # 历史文本时间戳是 UTC ISO-8601，按本地零点换算后做字符串比较
    day_start_iso = day_start.astimezone(dt_timezone.utc).isoformat()
    yesterday_active = UserDailyActivity.objects.filter(activity_date=yesterday)
    active_yesterday = yesterday_active.count()
    active_today = UserDailyActivity.objects.filter(activity_date=today).count()
    retained_today = UserDailyActivity.objects.filter(
        activity_date=today, user_id__in=yesterday_active.values("user_id")
    ).count()
    users_new = User.objects.filter(created_at__gte=day_start_iso).count()
    uv_today = VisitDaily.objects.filter(date=today).values_list("uv", flat=True).first() or 0
    topics_today = (
        ForumTopic.objects.filter(created_at__gte=day_start)
        .exclude(status=ForumTopic.STATUS_DELETED)
        .count()
    )
    murmurs_today = Murmur.objects.filter(is_deleted=False, created_at__gte=day_start_iso).count()
    imaging_by_status = {
        row["status"]: row["count"]
        for row in ImageGenerationJob.objects.filter(created_at__gte=day_start)
        .values("status")
        .annotate(count=Count("id"))
    }
    community = {
        "date": today,
        "users_total": _rows("users"),
        "users_new_today": users_new,
        "users_active_today": active_today,
        "users_active_yesterday": active_yesterday,
        "users_retained_today": retained_today,
        "retention_next_day": round(retained_today / active_yesterday * 100, 1) if active_yesterday else None,
        "topics_today": topics_today,
        "murmurs_today": murmurs_today,
        "imaging_completed_today": imaging_by_status.get("completed", 0),
        "imaging_failed_today": imaging_by_status.get("failed", 0),
        "uv_today": uv_today,
        "signup_conversion": round(users_new / uv_today * 100, 1) if uv_today else None,
    }

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
