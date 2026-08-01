"""
Base HTTP request handler (Template Method pattern).

AppHandler provides core request/response infrastructure:
- send_json, read_json_body, parse_cookies
- Session management (admin + user)
- Auth requirement strategies (Strategy pattern)
- Dashboard helpers (get_table_snapshot, dashboard_mask_value)

Routing is done via do_GET/do_POST/do_PUT/do_DELETE which delegate to
domain handler functions imported lazily from submodules.
"""
import json
import mimetypes
import sqlite3
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config import (
    ADMIN_SESSION_COOKIE,
    ADMIN_USERNAME,
    DASHBOARD_MASKED_COLUMNS,
    DASHBOARD_TABLE_ORDER,
    MATERIAL_DIR,
    SESSION_TTL_SECONDS,
    SERVER_RUNTIME,
    STATIC_DIR,
    STATIC_ASSET_CACHE_SECONDS,
    USER_SESSION_COOKIE,
    VIDEO_ASSET_CACHE_SECONDS,
)
from app.db import get_db, release_db
from app.utils.http_stream import stream_file_response
from app.services.session_store import session_get, session_delete, list_active_sessions
from app.routes import dispatch
from app.utils.helpers import (
    json_safe_value,
    now_iso,
    quote_ident,
)


class AppHandler(BaseHTTPRequestHandler):
    """Core HTTP handler — routing + shared infrastructure."""

    server_version = "KFlowHome/1.0"

    # ───────── Core request/response ─────────

    def finish(self):
        try:
            super().finish()
        finally:
            release_db()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.end_headers()

    def _dispatch_request(self, method: str, *, static_fallback: bool = False):
        path = urlparse(self.path).path
        if dispatch(self, method, path):
            return
        if static_fallback:
            self.serve_static(path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_GET(self):
        self._dispatch_request("GET", static_fallback=True)

    def do_POST(self):
        self._dispatch_request("POST")

    def do_PUT(self):
        self._dispatch_request("PUT")

    def do_DELETE(self):
        self._dispatch_request("DELETE")

    # ───────── Static file serving ─────────

    def serve_static(self, path: str):
        if path in {"/admin/login", "/admin/register"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login?next=/admin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in {"/admin", "/admin/bigscreen"} and not self.get_session():
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"/login?next={path}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/":
            rel = "index.html"
        elif path == "/admin":
            rel = "admin.html"
        elif path == "/admin/bigscreen":
            rel = "admin-bigscreen.html"
        elif path == "/login":
            rel = "user-login.html"
        elif path == "/account":
            rel = "account.html"
        elif path == "/points":
            rel = "points.html"
        elif path == "/cardloom":
            rel = "cardloom_official_website.html"
        elif path.startswith("/product/"):
            rel = "product.html"
        else:
            rel = path.lstrip("/")

        target = (STATIC_DIR / rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return self.send_error(HTTPStatus.FORBIDDEN)

        if not target.exists() or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)

        mime, _ = mimetypes.guess_type(str(target))
        mime = mime or "application/octet-stream"
        if mime.startswith("text/") and "charset=" not in mime.lower():
            mime = f"{mime}; charset=utf-8"

        stat = target.stat()
        etag = f'W/"{int(stat.st_mtime):x}-{stat.st_size:x}"'
        if_none_match = self.headers.get("If-None-Match", "").strip()
        cache_control = (
            "no-cache" if target.suffix.lower() == ".html"
            else f"public, max-age={STATIC_ASSET_CACHE_SECONDS}"
        )

        if if_none_match and etag in {tok.strip() for tok in if_none_match.split(",")}:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache_control)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        with target.open("rb") as f:
            data = f.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(data)

    def serve_material_file(self, path: str):
        rel = unquote(path.removeprefix("/material/"))
        if not rel or ".." in rel:
            return self.send_error(HTTPStatus.FORBIDDEN)
        target = (MATERIAL_DIR / rel).resolve()
        try:
            target.relative_to(MATERIAL_DIR.resolve())
        except ValueError:
            return self.send_error(HTTPStatus.FORBIDDEN)
        if not target.exists() or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        mime, _ = mimetypes.guess_type(str(target))
        mime = mime or "application/octet-stream"
        if target.suffix == ".mp4":
            mime = "video/mp4"
        stream_file_response(
            self,
            target,
            mime,
            cache_control=f"public, max-age={VIDEO_ASSET_CACHE_SECONDS}",
        )

    # ───────── JSON / SSE helpers ─────────

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload, status=HTTPStatus.OK):
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    # ───────── Cookie / Session helpers ─────────

    def parse_cookies(self):
        raw = self.headers.get("Cookie", "")
        cookies = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v
        return cookies

    # ─── Admin session ───

    def get_session(self):
        cookies = self.parse_cookies()
        token = cookies.get(ADMIN_SESSION_COOKIE)
        if token:
            sess = session_get(token)
            if sess:
                return token, sess

        # Fallback: check user_session for admin users (unified login)
        user_token = cookies.get(USER_SESSION_COOKIE)
        if not user_token:
            return None
        user_sess = session_get(user_token)
        if not user_sess or user_sess.get("role") != "user":
            return None
        username = user_sess.get("username", "")
        if username == ADMIN_USERNAME:
            return user_token, {
                "username": ADMIN_USERNAME,
                "is_super": True,
                "admin_level": 3,
                "role": "admin",
                "exp": user_sess["exp"],
            }
        conn = get_db()
        try:
            admin_row = conn.execute(
                "SELECT * FROM admin_accounts WHERE username = ?", (username,)
            ).fetchone()
        finally:
            conn.close()
        if admin_row:
            return user_token, {
                "username": admin_row["username"],
                "is_super": bool(admin_row["is_super"]),
                "admin_level": int(admin_row["admin_level"]),
                "role": "admin",
                "exp": user_sess["exp"],
            }
        return None

    def require_auth(self):
        if not self.get_session():
            self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def require_super_auth(self):
        sess = self.get_session()
        if not sess:
            self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        _, data = sess
        if not data.get("is_super"):
            self.send_json({"error": "super admin required"}, status=HTTPStatus.FORBIDDEN)
            return None
        return data

    def require_level2_auth(self):
        sess = self.get_session()
        if not sess:
            self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        _, data = sess
        if int(data.get("admin_level", 1)) < 2:
            self.send_json({"error": "lv2 admin required"}, status=HTTPStatus.FORBIDDEN)
            return None
        return data

    def require_level3_auth(self):
        sess = self.get_session()
        if not sess:
            self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        _, data = sess
        if int(data.get("admin_level", 1)) < 3:
            self.send_json({"error": "lv3 admin required"}, status=HTTPStatus.FORBIDDEN)
            return None
        return data

    # ─── User session ───

    def get_user_session(self):
        cookies = self.parse_cookies()
        token = cookies.get(USER_SESSION_COOKIE)
        if not token:
            return None
        sess = session_get(token)
        if not sess:
            return None
        if sess.get("role") != "user":
            return None
        return token, sess

    def require_user_auth(self):
        sess = self.get_user_session()
        if not sess:
            self.send_json({"error": "user login required"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        return sess

    # ───────── Path / value helpers ─────────

    def parse_path_int_id(self, path: str, prefix: str):
        if not path.startswith(prefix):
            return None
        tail = path[len(prefix):].strip("/")
        if not tail or "/" in tail:
            return None
        try:
            return int(tail)
        except ValueError:
            return None

    def dashboard_mask_value(self, column_name: str, value):
        if column_name not in DASHBOARD_MASKED_COLUMNS:
            return json_safe_value(value)
        text = str(value or "")
        if not text:
            return ""
        if len(text) <= 8:
            return "*" * len(text)
        return f"{text[:2]}***{text[-2:]}"

    def serialize_db_row(self, row: sqlite3.Row):
        return {key: self.dashboard_mask_value(key, row[key]) for key in row.keys()}

    _DASHBOARD_PREVIEW_ROWS = 10
    _DASHBOARD_MAX_LIMIT = 500

    def get_table_snapshot(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        limit: int | None = None,
        offset: int = 0,
    ):
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

        row_count = int(conn.execute(f"SELECT COUNT(*) FROM {ident}").fetchone()[0])

        if limit is not None:
            fetch_limit = max(0, min(int(limit), self._DASHBOARD_MAX_LIMIT))
            fetch_offset = max(0, int(offset))
            row_query = f"SELECT * FROM {ident}{order_clause} LIMIT ? OFFSET ?"
            row_items = [
                self.serialize_db_row(row)
                for row in conn.execute(row_query, (fetch_limit, fetch_offset)).fetchall()
            ]
        else:
            row_items = []
            fetch_limit = 0
            fetch_offset = 0

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
            "row_count": row_count,
            "columns": columns,
            "status_breakdown": status_breakdown,
            "rows": row_items,
            "limit": fetch_limit if limit is not None else 0,
            "offset": fetch_offset if limit is not None else 0,
            "has_more": (fetch_offset + len(row_items) < row_count) if limit is not None else (row_count > 0),
        }

    # ───────── Dashboard ─────────

    def dashboard_get(self):
        """Aggregated admin dashboard — table stats, service info, metrics."""
        sess = self.get_session()
        if not sess:
            return self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)

        _, admin = sess
        active_sessions = list_active_sessions()
        now_ts = time.time()

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
                self.get_table_snapshot(conn, table_name, limit=self._DASHBOARD_PREVIEW_ROWS)
                for table_name in DASHBOARD_TABLE_ORDER
                if table_name in available_table_names
            ]
        finally:
            conn.close()

        table_map = {table["name"]: table for table in tables}

        def table_count(name: str) -> int:
            return int(table_map.get(name, {}).get("row_count", 0))

        def status_count(name: str, wanted: str) -> int:
            table = table_map.get(name, {})
            for item in (table.get("status_breakdown") or []):
                if str(item.get("status") or "") == wanted:
                    return int(item.get("count") or 0)
            return 0

        total_rows = sum(int(table["row_count"]) for table in tables)
        self.send_json(
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
                    "started_at": SERVER_RUNTIME.get("started_at", ""),
                    "uptime_seconds": max(0, int(now_ts - float(SERVER_RUNTIME.get("started_at", now_ts)))),
                    "host": SERVER_RUNTIME.get("bound_host", ""),
                    "port": SERVER_RUNTIME.get("bound_port"),
                    "process_id": os.getpid(),
                    "db_status": "online",
                    "db_path": str(Path(__file__).resolve().parent.parent / "data" / "homepage.db"),
                    "session_ttl_seconds": SESSION_TTL_SECONDS,
                    "active_sessions": len(active_sessions),
                    "admin_sessions": sum(1 for item in active_sessions if item.get("role") == "admin"),
                    "user_sessions": sum(1 for item in active_sessions if item.get("role") == "user"),
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
                },
                "tables": tables,
            }
        )

    # ─── Product row serializer ───

    def product_row_dict(self, row: sqlite3.Row):
        return {
            "id": row["id"],
            "slug": row["slug"],
            "name": row["name"],
            "summary": row["summary"],
            "description": row["description"],
            "category": row["category"] if "category" in row.keys() else "",
            "tags": row["tags"] if "tags" in row.keys() else "",
            "announcement": row["announcement"] if "announcement" in row.keys() else "",
            "version": row["version"],
            "changelog": row["changelog"],
            "status": row["status"],
            "created_by": row["created_by"] if "created_by" in row.keys() else "",
            "file_name": row["file_name"],
            "file_path": row["file_path"],
            "file_size": row["file_size"],
            "file_sha256": row["file_sha256"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "published_at": row["published_at"],
            "download_count": row["download_count"] if "download_count" in row.keys() else 0,
            "download_url": f"/download/{row['slug']}",
        }

# Needed for dashboard_get which accesses os.getpid
import os
