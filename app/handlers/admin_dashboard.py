"""
Admin dashboard handler — table viewer, system metrics, key rotation info.
"""
import time
from datetime import datetime, timezone
from http import HTTPStatus

from app.config import (
    AGNES_KEY_ROTATION_CURSOR,
    AGNES_KEY_ROTATION_LOCK,
    AGNES_TASK_REFRESH_INTERVAL_SECONDS,
    CHAT_TOKEN_REFRESH_INTERVAL_SECONDS,
    DASHBOARD_MASKED_COLUMNS,
    DASHBOARD_TABLE_ORDER,
    DB_PATH,
    SESSION_TTL_SECONDS,
    SERVER_RUNTIME,
    SESSIONS,
)
from app.db import get_db
from app.utils.helpers import json_safe_value, mask_api_key, now_iso, quote_ident


def handle_admin_dashboard_get(handler):
    """GET /api/admin/dashboard — full system dashboard."""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return

    _, admin = sess
    now_ts = time.time()
    active_sessions = []
    for token, data in list(SESSIONS.items()):
        if float(data.get("exp", 0) or 0) < now_ts:
            SESSIONS.pop(token, None)
            continue
        active_sessions.append(data)

    conn = get_db()
    try:
        conn.execute("SELECT 1").fetchone()
        available_table_names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name COLLATE NOCASE ASC"
            ).fetchall()
        }
        tables = [
            _get_table_snapshot(handler, conn, table_name)
            for table_name in DASHBOARD_TABLE_ORDER
            if table_name in available_table_names
        ]
        enabled_key_rows = conn.execute(
            "SELECT id, label, api_key FROM agnes_api_keys WHERE enabled = 1 ORDER BY id ASC"
        ).fetchall()
        chat_token_totals = conn.execute(
            """
            SELECT
                COALESCE(SUM(session_count), 0) AS session_count,
                COALESCE(SUM(message_count), 0) AS message_count,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM agnes_chat_token_stats
            """
        ).fetchone()
    finally:
        conn.close()

    table_map = {table["name"]: table for table in tables}

    def table_count(name: str) -> int:
        return int(table_map.get(name, {}).get("row_count", 0))

    def table_rows_list(name: str):
        return table_map.get(name, {}).get("rows", [])

    def status_count(name: str, wanted: str) -> int:
        rows = table_rows_list(name)
        return sum(1 for row in rows if str(row.get("status") or "") == wanted)

    current_rotation = None
    if enabled_key_rows:
        with AGNES_KEY_ROTATION_LOCK:
            idx = AGNES_KEY_ROTATION_CURSOR % len(enabled_key_rows)
        current_key = enabled_key_rows[idx]
        current_rotation = {
            "current_index": idx + 1,
            "total": len(enabled_key_rows),
            "key_id": int(current_key["id"]),
            "label": current_key["label"] or "",
            "masked_key": mask_api_key(current_key["api_key"] or ""),
        }

    total_rows = sum(int(table["row_count"]) for table in tables)
    handler.send_json(
        {
            "generated_at": now_iso(),
            "viewer": {
                "username": admin.get("username", ""),
                "admin_level": int(admin.get("admin_level", 1)),
                "is_super": bool(admin.get("is_super")),
            },
            "service": {
                "status": "online",
                "server_time": now_iso(),
                "started_at": datetime.fromtimestamp(
                    float(SERVER_RUNTIME["started_at"]), timezone.utc
                ).isoformat(),
                "uptime_seconds": max(0, int(now_ts - float(SERVER_RUNTIME["started_at"]))),
                "host": SERVER_RUNTIME["bound_host"] or "127.0.0.1",
                "port": SERVER_RUNTIME["bound_port"],
                "process_id": os.getpid(),
                "db_status": "online",
                "db_path": str(DB_PATH),
                "session_ttl_seconds": SESSION_TTL_SECONDS,
                "active_sessions": len(active_sessions),
                "admin_sessions": sum(1 for item in active_sessions if item.get("role") == "admin"),
                "user_sessions": sum(1 for item in active_sessions if item.get("role") == "user"),
                "agnes_refresh_interval_seconds": AGNES_TASK_REFRESH_INTERVAL_SECONDS,
                "chat_token_refresh_interval_seconds": CHAT_TOKEN_REFRESH_INTERVAL_SECONDS,
                "chat_token_refreshed_at": SERVER_RUNTIME["chat_token_refreshed_at"],
                "agnes_rotation": current_rotation,
            },
            "metrics": {
                "table_count": len(tables),
                "total_row_count": total_rows,
                "products_total": table_count("products"),
                "products_published": status_count("products", "published"),
                "products_draft": status_count("products", "draft"),
                "downloads_total": table_count("downloads"),
                "users_total": table_count("users"),
                "subscribers_total": table_count("subscribers"),
                "admin_accounts_total": table_count("admin_accounts"),
                "pending_download_requests": status_count("download_requests", "pending"),
                "pending_publish_requests": status_count("publish_requests", "pending"),
                "pending_delete_requests": status_count("product_delete_requests", "pending"),
                "pending_video_requests": status_count("agnes_video_requests", "pending"),
                "agnes_keys_enabled": len(enabled_key_rows),
                "agnes_tasks_total": table_count("agnes_video_tasks"),
                "agnes_tasks_completed": status_count("agnes_video_tasks", "completed"),
                "agnes_tasks_failed": status_count("agnes_video_tasks", "failed"),
                "chat_sessions_total": int((chat_token_totals or {})["session_count"] if chat_token_totals else 0),
                "chat_messages_total": int((chat_token_totals or {})["message_count"] if chat_token_totals else 0),
                "chat_input_tokens_total": int((chat_token_totals or {})["input_tokens"] if chat_token_totals else 0),
                "chat_output_tokens_total": int((chat_token_totals or {})["output_tokens"] if chat_token_totals else 0),
                "chat_total_tokens_total": int((chat_token_totals or {})["total_tokens"] if chat_token_totals else 0),
            },
            "tables": tables,
        }
    )


def _mask_value(column_name: str, value):
    """Mask sensitive column values (password_hash, api_key, token)."""
    if column_name not in DASHBOARD_MASKED_COLUMNS:
        return json_safe_value(value)
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:2]}***{text[-2:]}"


def _serialize_db_row(row):
    """Serialize a sqlite3.Row to dict with masked sensitive columns."""
    return {key: _mask_value(key, row[key]) for key in row.keys()}


def _get_table_snapshot(handler, conn, table_name: str) -> dict:
    """Return a structured snapshot of one database table."""
    ident = quote_ident(table_name)
    column_rows = conn.execute(f"PRAGMA table_info({ident})").fetchall()
    columns = [
        {
            "name": row["name"],
            "type": row["type"] or "",
            "not_null": bool(row["notnull"]),
            "default": json_safe_value(row["dflt_value"]),
            "primary_key_index": int(row["pk"] or 0),
        }
        for row in column_rows
    ]
    column_names = [item["name"] for item in columns]
    order_clause = ""
    if "id" in column_names:
        order_clause = " ORDER BY id DESC"
    elif "updated_at" in column_names:
        order_clause = " ORDER BY updated_at DESC"
    elif "created_at" in column_names:
        order_clause = " ORDER BY created_at DESC"
    row_items = [
        _serialize_db_row(row)
        for row in conn.execute(f"SELECT * FROM {ident}{order_clause}").fetchall()
    ]
    status_breakdown = []
    if "status" in column_names:
        status_breakdown = [
            {
                "status": json_safe_value(row["status"]),
                "count": int(row["count"] or 0),
            }
            for row in conn.execute(
                f"SELECT status, COUNT(*) AS count FROM {ident} GROUP BY status ORDER BY count DESC, status ASC"
            ).fetchall()
        ]
    return {
        "name": table_name,
        "is_internal": table_name.startswith("sqlite_"),
        "row_count": len(row_items),
        "columns": columns,
        "status_breakdown": status_breakdown,
        "rows": row_items,
    }
