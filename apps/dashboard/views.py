from __future__ import annotations

import os
import time

from django.conf import settings
from django.db import connection
from django.views.decorators.http import require_GET

from apps.accounts.models import AdminAccount, User
from apps.core.permissions import require_admin
from apps.core.responses import json_ok
from apps.downloads.models import Download, DownloadRequest
from apps.catalog.models import Product
from apps.publishing.models import ProductDeleteRequest, PublishRequest

TABLES=["products","product_packages","product_versions","downloads","download_requests","publish_requests","publish_request_votes","product_delete_requests","users","point_accounts","point_ledger","user_daily_activity","download_entitlements","email_verification_codes","subscribers","user_subscriptions","admin_accounts","admin_upload_events","system_settings"]
MASKED={"password","password_hash","code_hash","token"}
STARTED_AT=time.time()


def mask(name,value):
    if name not in MASKED:return value.hex() if isinstance(value,bytes) else value
    text=str(value or "")
    return "" if not text else "*"*len(text) if len(text)<=8 else f"{text[:2]}***{text[-2:]}"


def snapshot(table):
    with connection.cursor() as cursor:
        columns=connection.introspection.get_table_description(cursor,table);names=[x.name for x in columns]
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
    return json_ok({
        "generated_at":__import__("django").utils.timezone.now().isoformat(),
        "viewer":{"username":request.kflow_admin["username"],"admin_level":request.kflow_admin["admin_level"],"is_super":request.kflow_admin["is_super"]},
        "service":{"status":"online","server_time":__import__("django").utils.timezone.now().isoformat(),"started_at":__import__("datetime").datetime.fromtimestamp(STARTED_AT,__import__("datetime").timezone.utc).isoformat(),"uptime_seconds":int(time.time()-STARTED_AT),"host":request.get_host().split(":")[0],"port":request.get_port(),"process_id":os.getpid(),"db_status":"online","db_path":str(settings.DATABASES["default"]["NAME"]),"session_ttl_seconds":settings.SESSION_COOKIE_AGE,"active_sessions":active_sessions,"admin_sessions":0,"user_sessions":active_sessions},
        "metrics":{"table_count":len(tables),"total_row_count":total,"products_total":Product.objects.count(),"products_published":Product.objects.filter(status="published").count(),"products_draft":Product.objects.filter(status="draft").count(),"downloads_total":Download.objects.count(),"users_total":User.objects.count(),"subscribers_total":0,"admin_accounts_total":AdminAccount.objects.count(),"pending_download_requests":DownloadRequest.objects.filter(status="pending").count(),"pending_publish_requests":PublishRequest.objects.filter(status="pending").count(),"pending_delete_requests":ProductDeleteRequest.objects.filter(status="pending").count()},
        "tables":tables,
    })
