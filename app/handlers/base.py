"""
Base HTTP request handler (Template Method pattern).

AppHandler provides core request/response infrastructure:
- send_json, read_json_body, parse_cookies
- Session management (admin + user)
- Auth requirement strategies (Strategy pattern)
- SSE helpers
- Dashboard helpers (get_table_snapshot, dashboard_mask_value)
- Agnes video/chat shared helpers

Routing is done via do_GET/do_POST/do_PUT/do_DELETE which delegate to
domain handler functions imported lazily from submodules.
"""
import json
import mimetypes
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config import (
    ADMIN_SESSION_COOKIE,
    ADMIN_USERNAME,
    AGNES_CHAT_MODEL_CONTROL_DEFAULTS,
    AGNES_FREE_VIDEO_LIMIT,
    AGNES_KEY_ROTATION_CURSOR,
    AGNES_KEY_ROTATION_LOCK,
    DASHBOARD_MASKED_COLUMNS,
    DASHBOARD_TABLE_ORDER,
    MATERIAL_DIR,
    SESSION_TTL_SECONDS,
    SERVER_RUNTIME,
    SESSIONS,
    STATIC_DIR,
    STATIC_ASSET_CACHE_SECONDS,
    USER_SESSION_COOKIE,
    VIDEO_ASSET_CACHE_SECONDS,
)
from app.db import get_db, begin_immediate_with_retry, release_db
from app.utils.http_stream import stream_file_response
from app.utils.helpers import (
    estimate_prompt_tokens_for_history,
    estimate_text_tokens_value as estimate_text_tokens,
    extract_video_url,
    json_safe_value,
    mask_api_key,
    normalize_chat_session_title,
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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Public / health
        if path == "/api/health":
            return self.send_json({"ok": True, "time": now_iso()})

        # User API
        if path == "/api/user/me":
            return self._call("auth_user", "handle_user_me")
        if path == "/api/account/me":
            return self._call("auth_user", "handle_account_me")
        if path == "/api/user/history":
            return self._call("user", "handle_user_history")
        if path == "/api/user/download-quota":
            return self._call("user", "handle_user_download_quota")
        if path == "/api/user/requests":
            return self._call("user", "handle_user_requests")
        if path == "/api/user/notifications":
            return self._call("user", "handle_user_notifications")
        if path == "/api/points/me":
            return self._call("points", "handle_points_me")
        if path == "/api/points/rules":
            return self._call("points", "handle_points_rules")
        if path == "/api/points/ledger":
            return self._call("points", "handle_points_ledger", self.path)
        if path == "/api/points/download-entitlements":
            return self._call("points", "handle_points_entitlements")

        # Admin GET routes (some need path for ID extraction)
        if path.startswith("/api/admin/download-requests"):
            return self._call("admin_requests", "handle_admin_download_requests_get", self.path)
        if path == "/api/admin/users":
            return self._call("auth_admin", "handle_admin_users_get")
        if path == "/api/admin/me":
            return self._call("auth_admin", "handle_admin_me")
        if path == "/api/admin/dashboard":
            return self.dashboard_get()
        if path == "/api/admin/tokens":
            return self._call("auth_admin", "handle_admin_tokens_get")
        if path == "/api/admin/agnes-keys":
            return self._call("admin_agnes_keys", "handle_admin_agnes_keys_get")
        if path == "/api/admin/upload-settings":
            return self._call("admin_settings", "handle_admin_upload_settings_get")
        if path == "/api/admin/points/settings":
            return self._call("points", "handle_admin_points_settings_get")
        if path == "/api/admin/points/accounts":
            return self._call("points", "handle_admin_points_accounts", self.path)
        if path == "/api/admin/chat-model-config":
            return self._call("agnes_chat", "handle_admin_chat_model_config_get")
        if path == "/api/admin/publish-requests":
            return self._call("publish", "handle_publish_requests_get")
        if path == "/api/admin/inbox":
            return self._call("publish", "handle_admin_inbox_get")

        # Public products
        if path == "/api/products":
            return self._call("product", "handle_public_products")
        if path == "/api/products/meta":
            return self._call("product", "handle_public_products_meta")
        if path.startswith("/api/products/"):
            return self._call("product", "handle_public_product_detail", path)

        # Admin products/versions
        if path.startswith("/api/admin/versions"):
            return self._call("admin_products", "handle_admin_versions_get", path)
        if path.startswith("/api/admin/products/") and path.endswith("/packages"):
            return self._call("admin_products", "handle_admin_packages_get", path)
        if path.startswith("/api/admin/products"):
            return self._call("admin_products", "handle_admin_products_get", self.path)

        # Agnes
        if path == "/api/agnes/tasks":
            return self._call("agnes_video", "handle_agnes_tasks_get")
        if path == "/api/agnes/quota":
            return self._call("agnes_video", "handle_agnes_quota_get")
        if path == "/api/agnes/runtime":
            return self._call("agnes_video", "handle_agnes_runtime_get")
        if path == "/api/agnes/chat-sessions":
            return self._call("agnes_chat", "handle_agnes_chat_sessions_get")
        if path == "/api/agnes/chat-config":
            return self._call("agnes_chat", "handle_agnes_chat_config_get")
        if path == "/api/agnes/public-videos":
            return self._call("agnes_video", "handle_agnes_public_videos_get")
        if path.startswith("/api/agnes/videos/"):
            return self._call("agnes_video", "handle_agnes_video_get", path)
        if path.startswith("/api/admin/agnes-video-requests"):
            return self._call("admin_requests", "handle_admin_agnes_video_requests_get", self.path)

        # Download
        if path.startswith("/download/"):
            return self._call("download", "handle_download", path)
        if path.startswith("/material/"):
            return self.serve_material_file(path)

        return self.serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Admin auth
        if path == "/api/admin/login":
            return self._call("auth_admin", "handle_admin_login")
        if path == "/api/admin/logout":
            return self._call("auth_admin", "handle_admin_logout")
        if path == "/api/admin/register":
            return self.send_json(
                {"error": "legacy admin registration disabled; use unified registration at /api/user/register"},
                status=HTTPStatus.GONE,
            )
        if path == "/api/admin/tokens":
            return self._call("auth_admin", "handle_admin_tokens_create")
        if path == "/api/admin/agnes-keys":
            return self._call("admin_agnes_keys", "handle_admin_agnes_keys_create")
        if path == "/api/admin/upload-settings":
            return self._call("admin_settings", "handle_admin_upload_settings_update")
        if path == "/api/admin/points/settings":
            return self._call("points", "handle_admin_points_settings_update")
        if path == "/api/admin/points/adjust":
            return self._call("points", "handle_admin_points_adjust")
        if path == "/api/admin/points/freeze":
            return self._call("points", "handle_admin_points_freeze")
        if path == "/api/admin/points/unfreeze":
            return self._call("points", "handle_admin_points_unfreeze")
        if path == "/api/admin/chat-model-config":
            return self._call("agnes_chat", "handle_admin_chat_model_config_update")
        if path == "/api/admin/publish-requests":
            return self._call("publish", "handle_publish_request_create")
        if path.startswith("/api/admin/publish-requests/") and path.endswith("/vote"):
            return self._call("publish", "handle_publish_request_vote", path)
        if path.startswith("/api/admin/delete-requests/") and path.endswith("/approve"):
            return self._call("publish", "handle_delete_request_approve", path)
        if path.startswith("/api/admin/delete-requests/") and path.endswith("/reject"):
            return self._call("publish", "handle_delete_request_reject", path)
        if path.startswith("/api/admin/versions/") and path.endswith("/rollback"):
            return self._call("admin_products", "handle_admin_version_rollback", path)

        # User auth
        if path == "/api/user/verification-code":
            return self._call("auth_user", "handle_user_verification_code")
        if path == "/api/user/register":
            return self._call("auth_user", "handle_user_register")
        if path == "/api/user/login":
            return self._call("auth_user", "handle_user_login")
        if path == "/api/user/email/bind":
            return self._call("auth_user", "handle_user_email_bind")
        if path == "/api/user/logout":
            return self._call("auth_user", "handle_user_logout")
        if path == "/api/points/redeem-download":
            return self._call("points", "handle_points_redeem_download")

        # Subscribe
        if path == "/api/subscribe":
            return self._call("subscribe", "handle_subscribe")

        # User download request / admin review
        if path.startswith("/api/products/") and path.endswith("/request-download"):
            return self._call("product", "handle_user_download_request", path)
        if path == "/api/admin/products":
            return self._call("admin_products", "handle_admin_products_create")
        if path.startswith("/api/admin/products/") and path.endswith("/upload"):
            return self._call("admin_products", "handle_admin_upload", path)
        if path.startswith("/api/admin/download-requests/") and path.endswith("/approve"):
            return self._call("admin_requests", "handle_admin_download_request_approve", path)
        if path.startswith("/api/admin/download-requests/") and path.endswith("/reject"):
            return self._call("admin_requests", "handle_admin_download_request_reject", path)

        if path.startswith('/api/admin/products/') and path.endswith('/upload-sessions'):
            return self._call('chunk_uploads', 'handle_admin_chunk_upload_create', path)
        if path.startswith('/api/admin/upload-sessions/') and path.endswith('/complete'):
            return self._call('chunk_uploads', 'handle_admin_chunk_upload_complete', path)
        if path.startswith('/api/admin/upload-sessions/') and '/chunks/' in path:
            return self._call('chunk_uploads', 'handle_admin_chunk_upload_chunk', path)

        # Agnes video
        if path == "/api/agnes/videos":
            return self._call("agnes_video", "handle_agnes_video_create")
        if path == "/api/agnes/requests":
            return self._call("agnes_video", "handle_agnes_video_request_create")
        if path == "/api/agnes/chat-sessions":
            return self._call("agnes_chat", "handle_agnes_chat_sessions_create")
        if path == "/api/agnes/chat":
            return self._call("agnes_chat", "handle_agnes_chat_create")

        # Admin agnes video request review
        if path.startswith("/api/admin/agnes-video-requests/") and path.endswith("/approve"):
            return self._call("admin_requests", "handle_admin_agnes_video_request_approve", path)
        if path.startswith("/api/admin/agnes-video-requests/") and path.endswith("/reject"):
            return self._call("admin_requests", "handle_admin_agnes_video_request_reject", path)

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/agnes/tasks/") and path.endswith("/public"):
            return self._call("agnes_video", "handle_agnes_task_public_update", path)
        if path.startswith("/api/admin/products/"):
            return self._call("admin_products", "handle_admin_products_update", path)
        if path.startswith("/api/admin/agnes-keys/"):
            return self._call("admin_agnes_keys", "handle_admin_agnes_keys_update", path)
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/agnes/chat-sessions/"):
            return self._call("agnes_chat", "handle_agnes_chat_session_delete", path)
        if path.startswith("/api/agnes/tasks/"):
            return self._call("agnes_video", "handle_agnes_task_delete", path)
        if path.startswith("/api/admin/packages/"):
            return self._call("admin_products", "handle_admin_packages_delete", path)
        if path.startswith("/api/admin/products/"):
            return self._call("admin_products", "handle_admin_products_delete", path)
        if path.startswith("/api/admin/agnes-keys/"):
            return self._call("admin_agnes_keys", "handle_admin_agnes_keys_delete", path)
        self.send_error(HTTPStatus.NOT_FOUND)

    # ───────── Lazy domain handler dispatch ─────────

    _HANDLER_MODULES = {}

    @classmethod
    def _get_handler_module(cls, name):
        """Lazy-import a domain handler module by short name."""
        if name not in cls._HANDLER_MODULES:
            import importlib
            cls._HANDLER_MODULES[name] = importlib.import_module(f"app.handlers.{name}")
        return cls._HANDLER_MODULES[name]

    def _call(self, module_name, func_name, *args):
        """Look up a domain handler function and call it with self + optional args."""
        mod = self._get_handler_module(module_name)
        func = getattr(mod, func_name, None)
        if func is None:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        return func(self, *args)

    # ───────── Static file serving ─────────

    def serve_static(self, path: str):
        if path in {"/admin/login", "/admin/register"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login?next=/admin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in {"/admin", "/admin/model-control", "/admin/bigscreen"} and not self.get_session():
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"/login?next={path}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/":
            rel = "index.html"
        elif path == "/admin":
            rel = "admin.html"
        elif path == "/admin/model-control":
            rel = "admin-model-control.html"
        elif path == "/admin/bigscreen":
            rel = "admin-bigscreen.html"
        elif path == "/login":
            rel = "user-login.html"
        elif path == "/account":
            rel = "account.html"
        elif path == "/agnes-chat":
            rel = "agnes-chat.html"
        elif path == "/agnes-video-v2":
            rel = "agnes-video-v2.html"
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

        with target.open("rb") as f:
            data = f.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if target.suffix.lower() == ".html":
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Cache-Control", f"public, max-age={STATIC_ASSET_CACHE_SECONDS}")
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

    def send_sse_headers(self, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def write_sse_data(self, payload):
        if isinstance(payload, (dict, list)):
            text = json.dumps(payload, ensure_ascii=False)
        else:
            text = str(payload)
        lines = text.splitlines() or [""]
        for line in lines:
            self.wfile.write(f"data: {line}\n".encode("utf-8"))
        self.wfile.write(b"\n")
        self.wfile.flush()

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
            sess = SESSIONS.get(token)
            if sess and sess["exp"] >= time.time():
                return token, sess
            if sess:
                SESSIONS.pop(token, None)

        # Fallback: check user_session for admin users (unified login)
        user_token = cookies.get(USER_SESSION_COOKIE)
        if not user_token:
            return None
        user_sess = SESSIONS.get(user_token)
        if not user_sess or user_sess.get("role") != "user":
            return None
        if user_sess["exp"] < time.time():
            SESSIONS.pop(user_token, None)
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
        sess = SESSIONS.get(token)
        if not sess:
            return None
        if sess["exp"] < time.time():
            SESSIONS.pop(token, None)
            return None
        if sess.get("role") != "user":
            return None
        # Registration is a hard authentication boundary. Sessions created by
        # the historical auto-register flow must not survive this rule change.
        if not sess.get("registration_verified"):
            conn = get_db()
            try:
                user_row = conn.execute(
                    "SELECT email_verified_at FROM users WHERE id = ?", (sess.get("user_id"),)
                ).fetchone()
            finally:
                conn.close()
            if not user_row or not user_row["email_verified_at"]:
                SESSIONS.pop(token, None)
                return None
            sess["registration_verified"] = True
        return token, sess

    def require_user_auth(self):
        sess = self.get_user_session()
        if not sess:
            self.send_json({"error": "user login required"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        return sess

    # ─── Agnes session ───

    def get_agnes_session(self):
        user_sess = self.get_user_session()
        if user_sess:
            _, user = user_sess
            return {
                "role": "user",
                "user_id": int(user.get("user_id") or 0),
                "username": str(user.get("username") or "").strip(),
            }
        admin_sess = self.get_session()
        if admin_sess:
            _, admin = admin_sess
            return {
                "role": "admin",
                "user_id": None,
                "username": str(admin.get("username") or "").strip(),
                "admin_level": int(admin.get("admin_level", 1)),
                "is_super": bool(admin.get("is_super")),
            }
        return None

    def require_agnes_auth(self):
        sess = self.get_agnes_session()
        if not sess:
            self.send_json({"error": "login required"}, status=HTTPStatus.UNAUTHORIZED)
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

    def get_table_snapshot(self, conn: sqlite3.Connection, table_name: str):
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
            self.serialize_db_row(row)
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

    # ───────── Dashboard ─────────

    def dashboard_get(self):
        """Aggregated admin dashboard — table stats, service info, metrics."""
        sess = self.get_session()
        if not sess:
            return self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)

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
                self.get_table_snapshot(conn, table_name)
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

    # ───────── Agnes shared helpers ─────────

    def pick_agnes_api_key(self, conn: sqlite3.Connection):
        global AGNES_KEY_ROTATION_CURSOR
        rows = conn.execute(
            "SELECT * FROM agnes_api_keys WHERE enabled = 1 ORDER BY id ASC"
        ).fetchall()
        if not rows:
            return None
        with AGNES_KEY_ROTATION_LOCK:
            idx = AGNES_KEY_ROTATION_CURSOR % len(rows)
            row = rows[idx]
            AGNES_KEY_ROTATION_CURSOR = (AGNES_KEY_ROTATION_CURSOR + 1) % len(rows)
        return row

    def list_enabled_agnes_keys(self, conn: sqlite3.Connection):
        return conn.execute("SELECT * FROM agnes_api_keys WHERE enabled = 1 ORDER BY id ASC").fetchall()

    def is_task_not_exist_payload(self, payload) -> bool:
        if not isinstance(payload, dict):
            return False
        code = str(payload.get("code") or "").strip().lower()
        message = str(payload.get("message") or "").strip().lower()
        return code == "task_not_exist" or message == "task_not_exist"

    def get_current_agnes_owner(self, auth_ctx=None):
        ctx = auth_ctx or self.get_agnes_session()
        if ctx and ctx.get("role") == "user":
            user_id = int(ctx.get("user_id") or 0)
            username = str(ctx.get("username") or "").strip()
            return {
                "owner_key": f"user:{user_id}",
                "owner_role": "user",
                "owner_name": username or f"user-{user_id}",
            }
        if ctx and ctx.get("role") == "admin":
            username = str(ctx.get("username") or "").strip()
            return {
                "owner_key": f"admin:{username or 'admin'}",
                "owner_role": "admin",
                "owner_name": username or "admin",
            }
        return {"owner_key": "guest:0", "owner_role": "guest", "owner_name": "guest"}

    # ─── Chat shared helpers ───

    def estimate_messages_prompt_tokens(self, session_row, messages) -> int:
        system_prompt = str((session_row["system_prompt"] if session_row else "") or "").strip()
        return estimate_prompt_tokens_for_history(system_prompt, messages)

    def get_chat_session_row_for_owner(self, conn: sqlite3.Connection, session_id: int, owner_key: str):
        return conn.execute(
            """
            SELECT *
            FROM agnes_chat_sessions
            WHERE id = ? AND owner_key = ?
            LIMIT 1
            """,
            (session_id, owner_key),
        ).fetchone()

    def create_chat_session_record(self, conn: sqlite3.Connection, owner: dict, auth_ctx, title: str, body: dict):
        now = now_iso()
        user_id = None
        if auth_ctx and auth_ctx.get("role") == "user":
            user_id = int(auth_ctx.get("user_id") or 0)
        resolved_title = normalize_chat_session_title(title)
        cur = conn.execute(
            """
            INSERT INTO agnes_chat_sessions (
                owner_key, owner_role, owner_name, user_id,
                title, model, system_prompt, enable_thinking,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner.get("owner_key", "guest:0"),
                owner.get("owner_role", "guest"),
                owner.get("owner_name", "guest"),
                user_id,
                resolved_title,
                str(body.get("model") or "agnes-2.0-flash"),
                str(body.get("system_prompt") or body.get("systemPrompt") or ""),
                1 if bool(body.get("enable_thinking")) else 0,
                now,
                now,
            ),
        )
        session_id = int(cur.lastrowid)
        return conn.execute("SELECT * FROM agnes_chat_sessions WHERE id = ?", (session_id,)).fetchone()

    def update_chat_session_record(self, conn: sqlite3.Connection, session_row, title: str, body: dict):
        now = now_iso()
        resolved_title = normalize_chat_session_title(title or session_row["title"] or "")
        conn.execute(
            """
            UPDATE agnes_chat_sessions
            SET title = ?,
                model = ?,
                system_prompt = ?,
                enable_thinking = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                resolved_title,
                str(body.get("model") or session_row["model"] or "agnes-2.0-flash"),
                str(body.get("system_prompt") or body.get("systemPrompt") or session_row["system_prompt"] or ""),
                1 if bool(body.get("enable_thinking")) else 0,
                now,
                int(session_row["id"]),
            ),
        )

    def create_chat_message_record(
        self,
        conn: sqlite3.Connection,
        session_id: int,
        role: str,
        content: str = "",
        thinking_text: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        token_source: str = "",
        task_id: str = "",
        status: str = "completed",
        error_text: str = "",
        finish_reason: str = "",
    ):
        now = now_iso()
        seq = int(
            conn.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM agnes_chat_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
        )
        cur = conn.execute(
            """
            INSERT INTO agnes_chat_messages (
                session_id, sequence_no, role, content, thinking_text,
                prompt_tokens, completion_tokens, total_tokens, token_source,
                task_id, status, error_text, finish_reason,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                seq,
                role,
                content or "",
                thinking_text or "",
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                int(total_tokens or 0),
                token_source or "",
                task_id or "",
                status or "completed",
                error_text or "",
                finish_reason or "",
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE agnes_chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        return int(cur.lastrowid)

    def serialize_chat_message(self, row: sqlite3.Row):
        return {
            "id": int(row["id"]),
            "role": row["role"] or "",
            "content": row["content"] or "",
            "thinking": row["thinking_text"] or "",
            "prompt_tokens": int(row["prompt_tokens"] or 0),
            "completion_tokens": int(row["completion_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "token_source": row["token_source"] or "",
            "task_id": row["task_id"] or "",
            "status": row["status"] or "completed",
            "error_text": row["error_text"] or "",
            "finish_reason": row["finish_reason"] or "",
            "created_at": row["created_at"] or "",
            "sequence_no": int(row["sequence_no"] or 0),
        }

    def serialize_chat_session(self, conn: sqlite3.Connection, row: sqlite3.Row):
        message_rows = conn.execute(
            """
            SELECT *
            FROM agnes_chat_messages
            WHERE session_id = ?
            ORDER BY sequence_no ASC, id ASC
            """,
            (int(row["id"]),),
        ).fetchall()
        return {
            "id": int(row["id"]),
            "title": row["title"] or "",
            "model": row["model"] or "agnes-2.0-flash",
            "system_prompt": row["system_prompt"] or "",
            "enable_thinking": bool(row["enable_thinking"]),
            "owner_role": row["owner_role"] or "",
            "owner_name": row["owner_name"] or "",
            "created_at": row["created_at"] or "",
            "updated_at": row["updated_at"] or "",
            "messages": [self.serialize_chat_message(item) for item in message_rows],
        }

    def create_chat_task_record(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        session_id: int,
        user_message_id: int,
        assistant_message_id: int,
        owner: dict,
        auth_ctx,
        model: str,
        upstream_payload: dict,
    ):
        now = now_iso()
        user_id = None
        if auth_ctx and auth_ctx.get("role") == "user":
            user_id = int(auth_ctx.get("user_id") or 0)
        conn.execute(
            """
            INSERT INTO agnes_chat_tasks (
                task_id, session_id, user_message_id, assistant_message_id,
                owner_key, owner_role, owner_name, user_id,
                model, request_payload, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                task_id,
                int(session_id),
                int(user_message_id) if user_message_id else None,
                int(assistant_message_id) if assistant_message_id else None,
                owner.get("owner_key", "guest:0"),
                owner.get("owner_role", "guest"),
                owner.get("owner_name", "guest"),
                user_id,
                model or "agnes-2.0-flash",
                json.dumps(upstream_payload, ensure_ascii=False),
                now,
                now,
            ),
        )

    def get_chat_model_config_row(self, conn: sqlite3.Connection):
        return conn.execute(
            """
            SELECT * FROM agnes_chat_model_config WHERE id = 1 LIMIT 1
            """
        ).fetchone()

    def serialize_chat_model_config(self, row):
        defaults = dict(AGNES_CHAT_MODEL_CONTROL_DEFAULTS)
        payload = {
            "default_model": defaults["default_model"],
            "default_system_prompt": defaults["default_system_prompt"],
            "default_temperature": defaults["default_temperature"],
            "default_max_tokens": defaults["default_max_tokens"],
            "default_enable_thinking": bool(defaults["default_enable_thinking"]),
            "context_window_messages": defaults["context_window_messages"],
            "thinking_context_window_messages": defaults["thinking_context_window_messages"],
            "summary_max_lines": defaults["summary_max_lines"],
            "summary_max_chars": defaults["summary_max_chars"],
            "thinking_summary_max_chars": defaults["thinking_summary_max_chars"],
            "retain_thinking_on_empty_content": bool(defaults["retain_thinking_on_empty_content"]),
            "updated_at": "",
            "updated_by": "",
        }
        if not row:
            return payload
        for key in ("default_model", "default_system_prompt", "updated_at", "updated_by"):
            payload[key] = row[key] or payload[key]
        for key in (
            "default_temperature", "default_max_tokens",
            "context_window_messages", "thinking_context_window_messages",
            "summary_max_lines", "summary_max_chars", "thinking_summary_max_chars",
        ):
            payload[key] = row[key] if row[key] is not None else payload[key]
        for key in ("default_enable_thinking", "retain_thinking_on_empty_content"):
            payload[key] = bool(row[key]) if row[key] is not None else payload[key]
        return payload

    def get_effective_chat_model_config(self, conn: sqlite3.Connection | None = None):
        own_conn = conn is None
        if own_conn:
            conn = get_db()
        try:
            row = self.get_chat_model_config_row(conn)
            return self.serialize_chat_model_config(row)
        finally:
            if own_conn and conn is not None:
                conn.close()

    def validate_chat_model_config_payload(self, body):
        if not isinstance(body, dict):
            return None, "invalid payload"
        defaults = dict(AGNES_CHAT_MODEL_CONTROL_DEFAULTS)
        data = {}
        data["default_model"] = str(body.get("default_model") or defaults["default_model"]).strip()[:120] or defaults["default_model"]
        data["default_system_prompt"] = str(
            body.get("default_system_prompt")
            if body.get("default_system_prompt") is not None
            else defaults["default_system_prompt"]
        ).strip()
        if not data["default_system_prompt"]:
            data["default_system_prompt"] = defaults["default_system_prompt"]
        data["default_system_prompt"] = data["default_system_prompt"][:8000]

        from app.utils.helpers import clamp_float_value, clamp_int_value
        data["default_temperature"] = clamp_float_value(body.get("default_temperature"), 0.0, 2.0, float(defaults["default_temperature"]))
        data["default_max_tokens"] = clamp_int_value(body.get("default_max_tokens"), 128, 65535, int(defaults["default_max_tokens"]))
        data["default_enable_thinking"] = bool(defaults["default_enable_thinking"] if "default_enable_thinking" not in body else body.get("default_enable_thinking"))
        data["context_window_messages"] = clamp_int_value(body.get("context_window_messages"), 1, 64, int(defaults["context_window_messages"]))
        data["thinking_context_window_messages"] = clamp_int_value(body.get("thinking_context_window_messages"), 1, 64, int(defaults["thinking_context_window_messages"]))
        data["summary_max_lines"] = clamp_int_value(body.get("summary_max_lines"), 0, 64, int(defaults["summary_max_lines"]))
        data["summary_max_chars"] = clamp_int_value(body.get("summary_max_chars"), 0, 12000, int(defaults["summary_max_chars"]))
        data["thinking_summary_max_chars"] = clamp_int_value(body.get("thinking_summary_max_chars"), 0, 12000, int(defaults["thinking_summary_max_chars"]))
        data["retain_thinking_on_empty_content"] = bool(defaults["retain_thinking_on_empty_content"] if "retain_thinking_on_empty_content" not in body else body.get("retain_thinking_on_empty_content"))

        if data["thinking_context_window_messages"] > data["context_window_messages"]:
            data["thinking_context_window_messages"] = data["context_window_messages"]
        if data["thinking_summary_max_chars"] > data["summary_max_chars"] and data["summary_max_chars"] > 0:
            data["thinking_summary_max_chars"] = data["summary_max_chars"]
        return data, ""

    # ─── Video quota helper ───

    def get_agnes_video_quota_summary(self, conn: sqlite3.Connection, user_id: int):
        used_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM agnes_video_usage_events WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        )
        approved_unused = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM agnes_video_requests
                WHERE user_id = ? AND status = 'approved' AND consumed_at IS NULL
                """,
                (user_id,),
            ).fetchone()[0]
        )
        has_pending = conn.execute(
            "SELECT 1 FROM agnes_video_requests WHERE user_id = ? AND status = 'pending' LIMIT 1",
            (user_id,),
        ).fetchone() is not None
        remaining_free = max(0, AGNES_FREE_VIDEO_LIMIT - used_count)
        can_create_now = remaining_free > 0 or approved_unused > 0
        return {
            "free_limit": AGNES_FREE_VIDEO_LIMIT,
            "used_count": used_count,
            "remaining_free": remaining_free,
            "approved_unused_count": approved_unused,
            "has_pending_request": has_pending,
            "can_create_now": can_create_now,
        }

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

    def upsert_agnes_task_binding(self, conn: sqlite3.Connection, task_id: str, api_key_id: int, owner: dict, payload: dict):
        now = now_iso()
        payload = payload if isinstance(payload, dict) else {}
        prev = conn.execute(
            "SELECT model, prompt, video_url FROM agnes_video_tasks WHERE task_id = ? LIMIT 1",
            (task_id,),
        ).fetchone()
        prev_model = str(prev["model"] or "") if prev else ""
        prev_prompt = str(prev["prompt"] or "") if prev else ""
        prev_video_url = str(prev["video_url"] or "") if prev and "video_url" in prev.keys() else ""
        model = str(payload.get("model") or prev_model or "")
        prompt = str(payload.get("prompt") or prev_prompt or "")
        video_url = extract_video_url(payload) or prev_video_url
        progress_raw = payload.get("progress", 0)
        try:
            progress = int(progress_raw)
        except (TypeError, ValueError):
            progress = 0
        last_error = ""
        if payload.get("status") == "failed":
            last_error = str(payload.get("message") or payload.get("error") or "").strip()
        conn.execute(
            """
            INSERT INTO agnes_video_tasks (
                task_id, api_key_id, owner_key, owner_role, owner_name,
                model, prompt, status, progress, video_url, seconds, last_error,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                api_key_id = excluded.api_key_id,
                owner_key = excluded.owner_key,
                owner_role = excluded.owner_role,
                owner_name = excluded.owner_name,
                model = excluded.model,
                prompt = excluded.prompt,
                status = excluded.status,
                progress = excluded.progress,
                video_url = excluded.video_url,
                seconds = excluded.seconds,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                task_id,
                api_key_id,
                owner.get("owner_key", ""),
                owner.get("owner_role", "guest"),
                owner.get("owner_name", "guest"),
                model,
                prompt,
                str(payload.get("status") or ""),
                progress,
                video_url,
                str(payload.get("seconds") or ""),
                last_error,
                now,
                now,
            ),
        )

    def get_task_bound_key(self, conn: sqlite3.Connection, task_id: str):
        return conn.execute(
            """
            SELECT k.*
            FROM agnes_video_tasks t
            JOIN agnes_api_keys k ON k.id = t.api_key_id
            WHERE t.task_id = ?
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()


# Needed for dashboard_get which accesses os.getpid
import os
