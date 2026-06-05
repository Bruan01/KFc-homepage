#!/usr/bin/env python3
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "homepage.db"
DB_BACKUP_PATHS = [
    DATA_DIR / "homepage.db.backup1",
    DATA_DIR / "homepage.db.backup2",
]

def load_dotenv(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_dotenv(BASE_DIR / ".env")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SESSION_TTL_SECONDS = 60 * 60 * 8
LV1_UPLOAD_SIZE_LIMIT = 30 * 1024 * 1024  # 30 MB
LV2_UPLOAD_SIZE_LIMIT = 100 * 1024 * 1024  # 100 MB
LV3_UPLOAD_SIZE_LIMIT = 100 * 1024 * 1024  # 100 MB
try:
    LV1_AUTO_PROMOTE_PROJECT_COUNT = max(1, int(os.getenv("LV1_AUTO_PROMOTE_PROJECT_COUNT", "1")))
except ValueError:
    LV1_AUTO_PROMOTE_PROJECT_COUNT = 1
try:
    PUBLISH_REVIEW_TIMEOUT_MINUTES = max(1, int(os.getenv("PUBLISH_REVIEW_TIMEOUT_MINUTES", "60")))
except ValueError:
    PUBLISH_REVIEW_TIMEOUT_MINUTES = 60
ALLOWED_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}
ADMIN_SESSION_COOKIE = "admin_session"
USER_SESSION_COOKIE = "user_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SESSIONS = {}
AGNES_KEY_ROTATION_LOCK = threading.Lock()
AGNES_KEY_ROTATION_CURSOR = 0
AGNES_TASK_REFRESH_INTERVAL_SECONDS = 10
AGNES_FREE_VIDEO_LIMIT = 5
AGNES_CHAT_API_BASE = os.getenv("AGNES_CHAT_API_BASE", "https://apihub.agnes-ai.com/v1").rstrip("/")
AGNES_CHAT_API_KEY = os.getenv("AGNES_CHAT_API_KEY", "").strip()
try:
    DB_BACKUP_INTERVAL_SECONDS = max(0, int(os.getenv("DB_BACKUP_INTERVAL_SECONDS", "86400")))
except ValueError:
    DB_BACKUP_INTERVAL_SECONDS = 86400
try:
    CHAT_TOKEN_REFRESH_INTERVAL_SECONDS = max(30, int(os.getenv("CHAT_TOKEN_REFRESH_INTERVAL_SECONDS", "300")))
except ValueError:
    CHAT_TOKEN_REFRESH_INTERVAL_SECONDS = 300
try:
    AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS = max(1, int(os.getenv("AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS", "1")))
except ValueError:
    AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS = 1
try:
    AGNES_CHAT_TASK_WORKER_COUNT = max(1, int(os.getenv("AGNES_CHAT_TASK_WORKER_COUNT", "2")))
except ValueError:
    AGNES_CHAT_TASK_WORKER_COUNT = 2
DASHBOARD_TABLE_ORDER = [
    "products",
    "product_versions",
    "downloads",
    "download_requests",
    "publish_requests",
    "publish_request_votes",
    "product_delete_requests",
    "users",
    "subscribers",
    "user_subscriptions",
    "admin_accounts",
    "admin_upload_events",
    "agnes_video_requests",
    "agnes_video_tasks",
    "agnes_video_usage_events",
    "agnes_chat_sessions",
    "agnes_chat_messages",
    "agnes_chat_tasks",
    "agnes_chat_token_stats",
    "agnes_chat_model_config",
]
DASHBOARD_MASKED_COLUMNS = {"password_hash", "api_key", "token"}
SERVER_RUNTIME = {
    "started_at": time.time(),
    "bound_host": "",
    "bound_port": None,
    "chat_token_refreshed_at": "",
}
AGNES_CHAT_MODEL_CONTROL_DEFAULTS = {
    "default_model": "agnes-2.0-flash",
    "default_system_prompt": "You are a helpful AI assistant.",
    "default_temperature": 0.7,
    "default_max_tokens": 2048,
    "default_enable_thinking": True,
    "context_window_messages": 12,
    "thinking_context_window_messages": 8,
    "summary_max_lines": 16,
    "summary_max_chars": 1800,
    "thinking_summary_max_chars": 1200,
    "retain_thinking_on_empty_content": True,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'

def _find_first_url(value):
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("http://") or s.startswith("https://"):
            return s
        return ""
    if isinstance(value, list):
        for item in value:
            hit = _find_first_url(item)
            if hit:
                return hit
        return ""
    if isinstance(value, dict):
        for key in ("video_url", "url", "download_url", "play_url"):
            hit = _find_first_url(value.get(key))
            if hit:
                return hit
        for nested in value.values():
            hit = _find_first_url(nested)
            if hit:
                return hit
    return ""

def extract_video_url(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("video_url", "videoUrl", "url", "download_url", "play_url"):
        hit = _find_first_url(payload.get(key))
        if hit:
            return hit
    for key in ("data", "result", "output", "outputs", "video", "videos"):
        if key in payload:
            hit = _find_first_url(payload.get(key))
            if hit:
                return hit
    return _find_first_url(payload)


def begin_immediate_with_retry(conn: sqlite3.Connection, retries: int = 8, base_delay: float = 0.05) -> None:
    for attempt in range(max(1, int(retries))):
        try:
            conn.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            if attempt >= retries - 1:
                raise
            sleep_s = base_delay * (2 ** min(attempt, 4))
            time.sleep(sleep_s)


def slugify(value: str) -> str:
    out = []
    for ch in value.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", "_"}:
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or f"product-{int(time.time())}"


def safe_filename(name: str) -> str:
    clean = "".join(ch for ch in name if ch.isalnum() or ch in {".", "-", "_"})
    clean = clean.strip(".")
    return clean or f"package-{int(time.time())}.zip"


def hash_password(password: str) -> str:
    iterations = 240000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    parts = (stored or "").split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        try:
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected = bytes.fromhex(parts[3])
        except (ValueError, TypeError):
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    return hmac.compare_digest(password, stored or "")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def choose_backup_target() -> Path:
    existing = []
    for idx, path in enumerate(DB_BACKUP_PATHS):
        if path.exists():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0
            existing.append((idx, mtime))
        else:
            return path
    existing.sort(key=lambda item: item[1])
    return DB_BACKUP_PATHS[existing[0][0]]


def get_latest_backup_mtime() -> float:
    latest_mtime = 0.0
    for path in DB_BACKUP_PATHS:
        if not path.exists():
            continue
        try:
            latest_mtime = max(latest_mtime, path.stat().st_mtime)
        except OSError:
            continue
    return latest_mtime


def should_run_db_backup(now_ts: float | None = None) -> bool:
    if DB_BACKUP_INTERVAL_SECONDS <= 0:
        return False
    if now_ts is None:
        now_ts = time.time()
    latest_mtime = get_latest_backup_mtime()
    if latest_mtime <= 0:
        return True
    return now_ts - latest_mtime >= DB_BACKUP_INTERVAL_SECONDS


def backup_database_once() -> Path | None:
    if not DB_PATH.exists():
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = choose_backup_target()
    temp_target = target.with_suffix(target.suffix + ".tmp")

    src = sqlite3.connect(DB_PATH, timeout=30.0)
    dst = sqlite3.connect(temp_target, timeout=30.0)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()

    os.replace(temp_target, target)
    return target


def normalize_chat_session_title(value: str, fallback: str = "New Chat") -> str:
    title = str(value or "").strip()
    return title[:120] if title else fallback


def estimate_text_tokens_value(text: str) -> int:
    raw = str(text or "").strip()
    if not raw:
        return 0
    return max(1, (len(raw.encode("utf-8")) + 3) // 4)


def estimate_prompt_tokens_for_history(system_prompt: str, messages) -> int:
    total = 0
    prompt = str(system_prompt or "").strip()
    if prompt:
        total += estimate_text_tokens_value(prompt)
    for item in messages or []:
        total += estimate_text_tokens_value(item.get("content") or "")
        total += estimate_text_tokens_value(item.get("thinking_text") or "")
        total += 4
    return total


def merge_stream_text(existing: str, incoming: str) -> str:
    base = str(existing or "")
    chunk = str(incoming or "")
    if not chunk:
        return base
    if not base:
        return chunk
    if chunk.startswith(base):
        return chunk
    if base.endswith(chunk):
        return base
    return base + chunk


def extract_chat_reasoning_text(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("reasoning_content", "reasoning", "thinking", "reasoning_text", "thought"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def generate_chat_task_id() -> str:
    return f"chat_{int(time.time() * 1000)}_{secrets.token_hex(6)}"


def pick_agnes_chat_api_key_raw(conn: sqlite3.Connection):
    rows = conn.execute("SELECT id, api_key FROM agnes_api_keys WHERE enabled = 1 ORDER BY id ASC").fetchall()
    if rows:
        global AGNES_KEY_ROTATION_CURSOR
        with AGNES_KEY_ROTATION_LOCK:
            idx = AGNES_KEY_ROTATION_CURSOR % len(rows)
            row = rows[idx]
            AGNES_KEY_ROTATION_CURSOR = (AGNES_KEY_ROTATION_CURSOR + 1) % len(rows)
        return int(row["id"]), str(row["api_key"] or "").strip()
    fallback_key = AGNES_CHAT_API_KEY.strip()
    return None, fallback_key


def call_agnes_chat_upstream_raw(payload, api_key: str = ""):
    resolved_api_key = (api_key or AGNES_CHAT_API_KEY).strip()
    if not resolved_api_key:
        return None, {"error": "agnes chat api key not configured"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }
    req = Request(
        url=f"{AGNES_CHAT_API_BASE}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(req, timeout=180) as resp:
            status = int(getattr(resp, "status", HTTPStatus.OK))
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
        ctype = (exc.headers.get("Content-Type") or "").lower()
    except URLError as exc:
        return None, {"error": "upstream unavailable", "detail": str(exc.reason)}
    except Exception as exc:
        return None, {"error": "upstream request failed", "detail": str(exc)}

    if not raw:
        return status, {}
    text = raw.decode("utf-8", errors="replace")
    if "application/json" in ctype:
        try:
            return status, json.loads(text)
        except Exception:
            return status, {"raw": text}
    return status, {"raw": text}


def open_agnes_chat_upstream_stream_raw(payload, api_key: str = ""):
    resolved_api_key = (api_key or AGNES_CHAT_API_KEY).strip()
    if not resolved_api_key:
        return None, None, None, {"error": "agnes chat api key not configured"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }
    req = Request(
        url=f"{AGNES_CHAT_API_BASE}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        resp = urlopen(req, timeout=180)
        status = int(getattr(resp, "status", HTTPStatus.OK))
        ctype = (resp.headers.get("Content-Type") or "").lower()
        return status, ctype, resp, None
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
        ctype = (exc.headers.get("Content-Type") or "").lower()
        text = raw.decode("utf-8", errors="replace") if raw else ""
        if "application/json" in ctype and text:
            try:
                return status, ctype, None, json.loads(text)
            except Exception:
                return status, ctype, None, {"raw": text}
        return status, ctype, None, {"raw": text} if text else {}
    except URLError as exc:
        return None, None, None, {"error": "upstream unavailable", "detail": str(exc.reason)}
    except Exception as exc:
        return None, None, None, {"error": "upstream request failed", "detail": str(exc)}


def parse_chat_sse_block_raw(block_text: str):
    lines = [line for line in str(block_text or "").splitlines() if line.startswith("data:")]
    if not lines:
        return None
    data_text = "\n".join(line[5:].lstrip() for line in lines).strip()
    if not data_text:
        return None
    if data_text == "[DONE]":
        return {"done": True, "content": "", "thinking": "", "usage": None, "finish_reason": "", "error": ""}
    try:
        payload = json.loads(data_text)
    except Exception:
        return None
    choice = ((payload.get("choices") or [{}])[0]) if isinstance(payload, dict) else {}
    delta = choice.get("delta") if isinstance(choice, dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    content = ""
    if isinstance(delta, dict):
        content = str(delta.get("content") or "")
    if not content and isinstance(message, dict):
        content = str(message.get("content") or "")
    thinking = ""
    for src in (delta if isinstance(delta, dict) else {}, message if isinstance(message, dict) else {}, choice, payload):
        if not isinstance(src, dict):
            continue
        thinking = str(
            src.get("reasoning_content")
            or src.get("reasoning")
            or src.get("thinking")
            or src.get("reasoning_text")
            or ""
        ).strip()
        if thinking:
            break
    error_text = ""
    if isinstance(payload, dict):
        if isinstance(payload.get("error"), str):
            error_text = payload.get("error") or ""
        elif isinstance(payload.get("error"), dict):
            error_text = str(payload.get("error", {}).get("message") or "")
    return {
        "done": False,
        "content": content,
        "thinking": thinking,
        "usage": payload.get("usage") if isinstance(payload, dict) else None,
        "finish_reason": str(choice.get("finish_reason") or "") if isinstance(choice, dict) else "",
        "error": error_text,
    }


def clamp_float_value(value, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def clamp_int_value(value, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                announcement TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT '0.1.0',
                changelog TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_by TEXT NOT NULL DEFAULT '',
                file_name TEXT,
                file_path TEXT,
                file_size INTEGER,
                file_sha256 TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                published_at TEXT
            );

            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                downloaded_at TEXT NOT NULL,
                ip TEXT,
                user_agent TEXT,
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS download_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                review_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by TEXT,
                consumed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS admin_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                is_super INTEGER NOT NULL DEFAULT 0,
                admin_level INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS admin_register_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                admin_level INTEGER NOT NULL DEFAULT 1,
                used_by_admin_id INTEGER,
                used_at TEXT,
                FOREIGN KEY(used_by_admin_id) REFERENCES admin_accounts(id)
            );

            CREATE TABLE IF NOT EXISTS admin_upload_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_username TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL,
                file_size INTEGER NOT NULL DEFAULT 0,
                UNIQUE(admin_username, product_id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS publish_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                requested_by TEXT NOT NULL,
                requester_level INTEGER NOT NULL,
                reviewer_scope TEXT NOT NULL,
                reviewer_pool_count INTEGER NOT NULL,
                reviewer_pool_weight INTEGER NOT NULL DEFAULT 0,
                approve_threshold_weight INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                decided_at TEXT,
                decided_note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS publish_request_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                reviewer_username TEXT NOT NULL,
                reviewer_level INTEGER NOT NULL,
                vote TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(request_id, reviewer_username),
                FOREIGN KEY(request_id) REFERENCES publish_requests(id)
            );

            CREATE TABLE IF NOT EXISTS product_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                announcement TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                changelog TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                file_name TEXT,
                file_path TEXT,
                file_size INTEGER,
                file_sha256 TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'snapshot',
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS product_delete_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL DEFAULT '',
                product_slug TEXT NOT NULL DEFAULT '',
                requested_by TEXT NOT NULL,
                requester_level INTEGER NOT NULL,
                owner_username TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                decided_at TEXT,
                decided_by TEXT,
                decision_note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'email',
                created_at TEXT NOT NULL,
                UNIQUE(email, channel)
            );

            CREATE TABLE IF NOT EXISTS user_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS agnes_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used_at TEXT,
                use_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS agnes_video_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                api_key_id INTEGER NOT NULL,
                owner_key TEXT NOT NULL DEFAULT '',
                owner_role TEXT NOT NULL DEFAULT 'guest',
                owner_name TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                progress INTEGER NOT NULL DEFAULT 0,
                video_url TEXT NOT NULL DEFAULT '',
                seconds TEXT NOT NULL DEFAULT '',
                is_public INTEGER NOT NULL DEFAULT 0,
                public_at TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(api_key_id) REFERENCES agnes_api_keys(id)
            );

            CREATE TABLE IF NOT EXISTS agnes_video_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                owner_key TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by TEXT,
                review_note TEXT NOT NULL DEFAULT '',
                consumed_at TEXT,
                consumed_task_id TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS agnes_video_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                owner_key TEXT NOT NULL,
                task_id TEXT NOT NULL,
                request_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(request_id) REFERENCES agnes_video_requests(id)
            );

            CREATE INDEX IF NOT EXISTS idx_agnes_video_requests_user_status
            ON agnes_video_requests(user_id, status);

            CREATE INDEX IF NOT EXISTS idx_agnes_video_usage_events_user
            ON agnes_video_usage_events(user_id);

            CREATE TABLE IF NOT EXISTS agnes_chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_key TEXT NOT NULL,
                owner_role TEXT NOT NULL DEFAULT 'guest',
                owner_name TEXT NOT NULL DEFAULT '',
                user_id INTEGER,
                title TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT 'agnes-2.0-flash',
                system_prompt TEXT NOT NULL DEFAULT '',
                enable_thinking INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS agnes_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                sequence_no INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                thinking_text TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                token_source TEXT NOT NULL DEFAULT '',
                task_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'completed',
                error_text TEXT NOT NULL DEFAULT '',
                finish_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES agnes_chat_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS agnes_chat_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                session_id INTEGER NOT NULL,
                user_message_id INTEGER,
                assistant_message_id INTEGER,
                owner_key TEXT NOT NULL,
                owner_role TEXT NOT NULL DEFAULT 'guest',
                owner_name TEXT NOT NULL DEFAULT '',
                user_id INTEGER,
                model TEXT NOT NULL DEFAULT 'agnes-2.0-flash',
                request_payload TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                api_key_id INTEGER,
                response_content TEXT NOT NULL DEFAULT '',
                response_thinking TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                finish_reason TEXT NOT NULL DEFAULT '',
                error_text TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES agnes_chat_sessions(id),
                FOREIGN KEY(user_message_id) REFERENCES agnes_chat_messages(id),
                FOREIGN KEY(assistant_message_id) REFERENCES agnes_chat_messages(id),
                FOREIGN KEY(api_key_id) REFERENCES agnes_api_keys(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS agnes_chat_token_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_key TEXT NOT NULL UNIQUE,
                owner_role TEXT NOT NULL DEFAULT 'guest',
                owner_name TEXT NOT NULL DEFAULT '',
                user_id INTEGER,
                session_count INTEGER NOT NULL DEFAULT 0,
                message_count INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS agnes_chat_model_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                default_model TEXT NOT NULL DEFAULT 'agnes-2.0-flash',
                default_system_prompt TEXT NOT NULL DEFAULT 'You are a helpful AI assistant.',
                default_temperature REAL NOT NULL DEFAULT 0.7,
                default_max_tokens INTEGER NOT NULL DEFAULT 2048,
                default_enable_thinking INTEGER NOT NULL DEFAULT 1,
                context_window_messages INTEGER NOT NULL DEFAULT 12,
                thinking_context_window_messages INTEGER NOT NULL DEFAULT 8,
                summary_max_lines INTEGER NOT NULL DEFAULT 16,
                summary_max_chars INTEGER NOT NULL DEFAULT 1800,
                thinking_summary_max_chars INTEGER NOT NULL DEFAULT 1200,
                retain_thinking_on_empty_content INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_agnes_chat_sessions_owner
            ON agnes_chat_sessions(owner_key, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_agnes_chat_messages_session_seq
            ON agnes_chat_messages(session_id, sequence_no ASC);

            CREATE INDEX IF NOT EXISTS idx_agnes_chat_tasks_status_created
            ON agnes_chat_tasks(status, created_at ASC);
            """
        )

        cols = [r["name"] for r in conn.execute("PRAGMA table_info(downloads)").fetchall()]
        if "user_id" not in cols:
            conn.execute("ALTER TABLE downloads ADD COLUMN user_id INTEGER")
        if "request_id" not in cols:
            conn.execute("ALTER TABLE downloads ADD COLUMN request_id INTEGER")

        product_cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
        if "created_by" not in product_cols:
            conn.execute("ALTER TABLE products ADD COLUMN created_by TEXT NOT NULL DEFAULT ''")
        if "category" not in product_cols:
            conn.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT ''")
        if "tags" not in product_cols:
            conn.execute("ALTER TABLE products ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
        if "announcement" not in product_cols:
            conn.execute("ALTER TABLE products ADD COLUMN announcement TEXT NOT NULL DEFAULT ''")

        user_cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "email" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")

        version_cols = [r["name"] for r in conn.execute("PRAGMA table_info(product_versions)").fetchall()]
        if "category" not in version_cols:
            conn.execute("ALTER TABLE product_versions ADD COLUMN category TEXT NOT NULL DEFAULT ''")
        if "tags" not in version_cols:
            conn.execute("ALTER TABLE product_versions ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
        if "announcement" not in version_cols:
            conn.execute("ALTER TABLE product_versions ADD COLUMN announcement TEXT NOT NULL DEFAULT ''")

        admin_cols = [r["name"] for r in conn.execute("PRAGMA table_info(admin_accounts)").fetchall()]
        if "admin_level" not in admin_cols:
            conn.execute("ALTER TABLE admin_accounts ADD COLUMN admin_level INTEGER NOT NULL DEFAULT 1")

        token_cols = [r["name"] for r in conn.execute("PRAGMA table_info(admin_register_tokens)").fetchall()]
        if "admin_level" not in token_cols:
            conn.execute("ALTER TABLE admin_register_tokens ADD COLUMN admin_level INTEGER NOT NULL DEFAULT 1")

        publish_cols = [r["name"] for r in conn.execute("PRAGMA table_info(publish_requests)").fetchall()]
        if "reviewer_pool_weight" not in publish_cols:
            conn.execute("ALTER TABLE publish_requests ADD COLUMN reviewer_pool_weight INTEGER NOT NULL DEFAULT 0")
        if "approve_threshold_weight" not in publish_cols:
            conn.execute("ALTER TABLE publish_requests ADD COLUMN approve_threshold_weight INTEGER NOT NULL DEFAULT 0")
        if "expires_at" not in publish_cols:
            conn.execute("ALTER TABLE publish_requests ADD COLUMN expires_at TEXT")

        agnes_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agnes_api_keys)").fetchall()]
        if "label" not in agnes_cols:
            conn.execute("ALTER TABLE agnes_api_keys ADD COLUMN label TEXT NOT NULL DEFAULT ''")
        if "enabled" not in agnes_cols:
            conn.execute("ALTER TABLE agnes_api_keys ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        if "created_by" not in agnes_cols:
            conn.execute("ALTER TABLE agnes_api_keys ADD COLUMN created_by TEXT NOT NULL DEFAULT ''")
        if "created_at" not in agnes_cols:
            conn.execute("ALTER TABLE agnes_api_keys ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in agnes_cols:
            conn.execute("ALTER TABLE agnes_api_keys ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
        if "last_used_at" not in agnes_cols:
            conn.execute("ALTER TABLE agnes_api_keys ADD COLUMN last_used_at TEXT")
        if "use_count" not in agnes_cols:
            conn.execute("ALTER TABLE agnes_api_keys ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0")

        agnes_task_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agnes_video_tasks)").fetchall()]
        if "owner_key" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN owner_key TEXT NOT NULL DEFAULT ''")
        if "owner_role" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN owner_role TEXT NOT NULL DEFAULT 'guest'")
        if "owner_name" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN owner_name TEXT NOT NULL DEFAULT ''")
        if "model" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN model TEXT NOT NULL DEFAULT ''")
        if "prompt" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN prompt TEXT NOT NULL DEFAULT ''")
        if "status" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN status TEXT NOT NULL DEFAULT ''")
        if "progress" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN progress INTEGER NOT NULL DEFAULT 0")
        if "video_url" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN video_url TEXT NOT NULL DEFAULT ''")
        if "seconds" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN seconds TEXT NOT NULL DEFAULT ''")
        if "is_public" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0")
        if "public_at" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN public_at TEXT")
        if "last_error" not in agnes_task_cols:
            conn.execute("ALTER TABLE agnes_video_tasks ADD COLUMN last_error TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agnes_video_tasks_public ON agnes_video_tasks(is_public, updated_at)"
        )

        agnes_req_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agnes_video_requests)").fetchall()]
        if "owner_key" not in agnes_req_cols:
            conn.execute("ALTER TABLE agnes_video_requests ADD COLUMN owner_key TEXT NOT NULL DEFAULT ''")
        if "reason" not in agnes_req_cols:
            conn.execute("ALTER TABLE agnes_video_requests ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
        if "status" not in agnes_req_cols:
            conn.execute("ALTER TABLE agnes_video_requests ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
        if "reviewed_at" not in agnes_req_cols:
            conn.execute("ALTER TABLE agnes_video_requests ADD COLUMN reviewed_at TEXT")
        if "reviewed_by" not in agnes_req_cols:
            conn.execute("ALTER TABLE agnes_video_requests ADD COLUMN reviewed_by TEXT")
        if "review_note" not in agnes_req_cols:
            conn.execute("ALTER TABLE agnes_video_requests ADD COLUMN review_note TEXT NOT NULL DEFAULT ''")
        if "consumed_at" not in agnes_req_cols:
            conn.execute("ALTER TABLE agnes_video_requests ADD COLUMN consumed_at TEXT")
        if "consumed_task_id" not in agnes_req_cols:
            conn.execute("ALTER TABLE agnes_video_requests ADD COLUMN consumed_task_id TEXT NOT NULL DEFAULT ''")

        chat_session_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agnes_chat_sessions)").fetchall()]
        if "owner_key" not in chat_session_cols:
            conn.execute("ALTER TABLE agnes_chat_sessions ADD COLUMN owner_key TEXT NOT NULL DEFAULT ''")
        if "owner_role" not in chat_session_cols:
            conn.execute("ALTER TABLE agnes_chat_sessions ADD COLUMN owner_role TEXT NOT NULL DEFAULT 'guest'")
        if "owner_name" not in chat_session_cols:
            conn.execute("ALTER TABLE agnes_chat_sessions ADD COLUMN owner_name TEXT NOT NULL DEFAULT ''")
        if "user_id" not in chat_session_cols:
            conn.execute("ALTER TABLE agnes_chat_sessions ADD COLUMN user_id INTEGER")
        if "title" not in chat_session_cols:
            conn.execute("ALTER TABLE agnes_chat_sessions ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        if "model" not in chat_session_cols:
            conn.execute("ALTER TABLE agnes_chat_sessions ADD COLUMN model TEXT NOT NULL DEFAULT 'agnes-2.0-flash'")
        if "system_prompt" not in chat_session_cols:
            conn.execute("ALTER TABLE agnes_chat_sessions ADD COLUMN system_prompt TEXT NOT NULL DEFAULT ''")
        if "enable_thinking" not in chat_session_cols:
            conn.execute("ALTER TABLE agnes_chat_sessions ADD COLUMN enable_thinking INTEGER NOT NULL DEFAULT 0")

        chat_message_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agnes_chat_messages)").fetchall()]
        if "sequence_no" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN sequence_no INTEGER NOT NULL DEFAULT 0")
        if "thinking_text" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN thinking_text TEXT NOT NULL DEFAULT ''")
        if "prompt_tokens" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0")
        if "completion_tokens" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0")
        if "total_tokens" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN total_tokens INTEGER NOT NULL DEFAULT 0")
        if "token_source" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN token_source TEXT NOT NULL DEFAULT ''")
        if "task_id" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN task_id TEXT NOT NULL DEFAULT ''")
        if "status" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
        if "error_text" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN error_text TEXT NOT NULL DEFAULT ''")
        if "finish_reason" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN finish_reason TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in chat_message_cols:
            conn.execute("ALTER TABLE agnes_chat_messages ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agnes_chat_messages_task ON agnes_chat_messages(task_id)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agnes_chat_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                session_id INTEGER NOT NULL,
                user_message_id INTEGER,
                assistant_message_id INTEGER,
                owner_key TEXT NOT NULL,
                owner_role TEXT NOT NULL DEFAULT 'guest',
                owner_name TEXT NOT NULL DEFAULT '',
                user_id INTEGER,
                model TEXT NOT NULL DEFAULT 'agnes-2.0-flash',
                request_payload TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                api_key_id INTEGER,
                response_content TEXT NOT NULL DEFAULT '',
                response_thinking TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                finish_reason TEXT NOT NULL DEFAULT '',
                error_text TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES agnes_chat_sessions(id),
                FOREIGN KEY(user_message_id) REFERENCES agnes_chat_messages(id),
                FOREIGN KEY(assistant_message_id) REFERENCES agnes_chat_messages(id),
                FOREIGN KEY(api_key_id) REFERENCES agnes_api_keys(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        chat_task_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agnes_chat_tasks)").fetchall()]
        if "user_message_id" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN user_message_id INTEGER")
        if "assistant_message_id" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN assistant_message_id INTEGER")
        if "owner_key" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN owner_key TEXT NOT NULL DEFAULT ''")
        if "owner_role" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN owner_role TEXT NOT NULL DEFAULT 'guest'")
        if "owner_name" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN owner_name TEXT NOT NULL DEFAULT ''")
        if "user_id" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN user_id INTEGER")
        if "model" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN model TEXT NOT NULL DEFAULT 'agnes-2.0-flash'")
        if "request_payload" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN request_payload TEXT NOT NULL DEFAULT ''")
        if "status" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'queued'")
        if "api_key_id" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN api_key_id INTEGER")
        if "response_content" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN response_content TEXT NOT NULL DEFAULT ''")
        if "response_thinking" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN response_thinking TEXT NOT NULL DEFAULT ''")
        if "prompt_tokens" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0")
        if "completion_tokens" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0")
        if "total_tokens" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN total_tokens INTEGER NOT NULL DEFAULT 0")
        if "finish_reason" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN finish_reason TEXT NOT NULL DEFAULT ''")
        if "error_text" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN error_text TEXT NOT NULL DEFAULT ''")
        if "attempts" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        if "started_at" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN started_at TEXT")
        if "completed_at" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN completed_at TEXT")
        if "updated_at" not in chat_task_cols:
            conn.execute("ALTER TABLE agnes_chat_tasks ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agnes_chat_tasks_status_created ON agnes_chat_tasks(status, created_at ASC)")

        chat_stat_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agnes_chat_token_stats)").fetchall()]
        if "owner_role" not in chat_stat_cols:
            conn.execute("ALTER TABLE agnes_chat_token_stats ADD COLUMN owner_role TEXT NOT NULL DEFAULT 'guest'")
        if "owner_name" not in chat_stat_cols:
            conn.execute("ALTER TABLE agnes_chat_token_stats ADD COLUMN owner_name TEXT NOT NULL DEFAULT ''")
        if "user_id" not in chat_stat_cols:
            conn.execute("ALTER TABLE agnes_chat_token_stats ADD COLUMN user_id INTEGER")
        if "session_count" not in chat_stat_cols:
            conn.execute("ALTER TABLE agnes_chat_token_stats ADD COLUMN session_count INTEGER NOT NULL DEFAULT 0")
        if "message_count" not in chat_stat_cols:
            conn.execute("ALTER TABLE agnes_chat_token_stats ADD COLUMN message_count INTEGER NOT NULL DEFAULT 0")
        if "input_tokens" not in chat_stat_cols:
            conn.execute("ALTER TABLE agnes_chat_token_stats ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0")
        if "output_tokens" not in chat_stat_cols:
            conn.execute("ALTER TABLE agnes_chat_token_stats ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0")
        if "total_tokens" not in chat_stat_cols:
            conn.execute("ALTER TABLE agnes_chat_token_stats ADD COLUMN total_tokens INTEGER NOT NULL DEFAULT 0")

        chat_model_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agnes_chat_model_config)").fetchall()]
        if "default_model" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN default_model TEXT NOT NULL DEFAULT 'agnes-2.0-flash'")
        if "default_system_prompt" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN default_system_prompt TEXT NOT NULL DEFAULT 'You are a helpful AI assistant.'")
        if "default_temperature" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN default_temperature REAL NOT NULL DEFAULT 0.7")
        if "default_max_tokens" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN default_max_tokens INTEGER NOT NULL DEFAULT 2048")
        if "default_enable_thinking" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN default_enable_thinking INTEGER NOT NULL DEFAULT 1")
        if "context_window_messages" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN context_window_messages INTEGER NOT NULL DEFAULT 12")
        if "thinking_context_window_messages" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN thinking_context_window_messages INTEGER NOT NULL DEFAULT 8")
        if "summary_max_lines" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN summary_max_lines INTEGER NOT NULL DEFAULT 16")
        if "summary_max_chars" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN summary_max_chars INTEGER NOT NULL DEFAULT 1800")
        if "thinking_summary_max_chars" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN thinking_summary_max_chars INTEGER NOT NULL DEFAULT 1200")
        if "retain_thinking_on_empty_content" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN retain_thinking_on_empty_content INTEGER NOT NULL DEFAULT 1")
        if "updated_at" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
        if "updated_by" not in chat_model_cols:
            conn.execute("ALTER TABLE agnes_chat_model_config ADD COLUMN updated_by TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            INSERT OR IGNORE INTO agnes_chat_model_config (
                id, default_model, default_system_prompt, default_temperature, default_max_tokens,
                default_enable_thinking, context_window_messages, thinking_context_window_messages,
                summary_max_lines, summary_max_chars, thinking_summary_max_chars,
                retain_thinking_on_empty_content, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["default_model"],
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["default_system_prompt"],
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["default_temperature"],
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["default_max_tokens"],
                1 if AGNES_CHAT_MODEL_CONTROL_DEFAULTS["default_enable_thinking"] else 0,
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["context_window_messages"],
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["thinking_context_window_messages"],
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["summary_max_lines"],
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["summary_max_chars"],
                AGNES_CHAT_MODEL_CONTROL_DEFAULTS["thinking_summary_max_chars"],
                1 if AGNES_CHAT_MODEL_CONTROL_DEFAULTS["retain_thinking_on_empty_content"] else 0,
                now_iso(),
                "system",
            ),
        )
        conn.commit()
    finally:
        conn.close()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "KFlowHome/1.0"

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            return self.send_json({"ok": True, "time": now_iso()})
        if path == "/api/user/me":
            return self.handle_user_me()
        if path == "/api/account/me":
            return self.handle_account_me()
        if path == "/api/user/history":
            return self.handle_user_history()
        if path == "/api/user/download-quota":
            return self.handle_user_download_quota()
        if path == "/api/user/requests":
            return self.handle_user_requests()
        if path == "/api/user/notifications":
            return self.handle_user_notifications()
        if path.startswith("/api/admin/download-requests"):
            return self.handle_admin_download_requests_get(path)
        if path == "/api/products":
            return self.handle_public_products()
        if path == "/api/products/meta":
            return self.handle_public_products_meta()
        if path.startswith("/api/products/"):
            return self.handle_public_product_detail(path)
        if path.startswith("/api/admin/products"):
            return self.handle_admin_products_get(path)
        if path.startswith("/api/admin/versions"):
            return self.handle_admin_versions_get(path)
        if path == "/api/admin/me":
            return self.handle_admin_me()
        if path == "/api/admin/dashboard":
            return self.handle_admin_dashboard_get()
        if path == "/api/admin/tokens":
            return self.handle_admin_tokens_get()
        if path == "/api/admin/agnes-keys":
            return self.handle_admin_agnes_keys_get()
        if path == "/api/admin/chat-model-config":
            return self.handle_admin_chat_model_config_get()
        if path == "/api/admin/publish-requests":
            return self.handle_publish_requests_get()
        if path == "/api/admin/inbox":
            return self.handle_admin_inbox_get()
        if path == "/api/agnes/tasks":
            return self.handle_agnes_tasks_get()
        if path == "/api/agnes/quota":
            return self.handle_agnes_quota_get()
        if path == "/api/agnes/runtime":
            return self.handle_agnes_runtime_get()
        if path == "/api/agnes/chat-sessions":
            return self.handle_agnes_chat_sessions_get()
        if path == "/api/agnes/chat-config":
            return self.handle_agnes_chat_config_get()
        if path == "/api/agnes/public-videos":
            return self.handle_agnes_public_videos_get()
        if path.startswith("/api/agnes/videos/"):
            return self.handle_agnes_video_get(path)
        if path.startswith("/api/admin/agnes-video-requests"):
            return self.handle_admin_agnes_video_requests_get(path)
        if path.startswith("/download/"):
            return self.handle_download(path)
        return self.serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/admin/login":
            return self.handle_admin_login()
        if path == "/api/admin/logout":
            return self.handle_admin_logout()
        if path == "/api/admin/register":
            return self.handle_admin_register()
        if path == "/api/admin/tokens":
            return self.handle_admin_tokens_create()
        if path == "/api/admin/agnes-keys":
            return self.handle_admin_agnes_keys_create()
        if path == "/api/admin/chat-model-config":
            return self.handle_admin_chat_model_config_update()
        if path == "/api/admin/publish-requests":
            return self.handle_publish_request_create()
        if path.startswith("/api/admin/publish-requests/") and path.endswith("/vote"):
            return self.handle_publish_request_vote(path)
        if path.startswith("/api/admin/delete-requests/") and path.endswith("/approve"):
            return self.handle_delete_request_approve(path)
        if path.startswith("/api/admin/delete-requests/") and path.endswith("/reject"):
            return self.handle_delete_request_reject(path)
        if path.startswith("/api/admin/versions/") and path.endswith("/rollback"):
            return self.handle_admin_version_rollback(path)
        if path == "/api/user/login":
            return self.handle_user_login()
        if path == "/api/user/logout":
            return self.handle_user_logout()
        if path == "/api/subscribe":
            return self.handle_subscribe()
        if path.startswith("/api/products/") and path.endswith("/request-download"):
            return self.handle_user_download_request(path)
        if path == "/api/admin/products":
            return self.handle_admin_products_create()
        if path.startswith("/api/admin/products/") and path.endswith("/upload"):
            return self.handle_admin_upload(path)
        if path.startswith("/api/admin/download-requests/") and path.endswith("/approve"):
            return self.handle_admin_download_request_approve(path)
        if path.startswith("/api/admin/download-requests/") and path.endswith("/reject"):
            return self.handle_admin_download_request_reject(path)
        if path == "/api/agnes/videos":
            return self.handle_agnes_video_create()
        if path == "/api/agnes/chat-sessions":
            return self.handle_agnes_chat_sessions_create()
        if path == "/api/agnes/chat":
            return self.handle_agnes_chat_create()
        if path == "/api/agnes/requests":
            return self.handle_agnes_video_request_create()
        if path.startswith("/api/admin/agnes-video-requests/") and path.endswith("/approve"):
            return self.handle_admin_agnes_video_request_approve(path)
        if path.startswith("/api/admin/agnes-video-requests/") and path.endswith("/reject"):
            return self.handle_admin_agnes_video_request_reject(path)

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/agnes/tasks/") and path.endswith("/public"):
            return self.handle_agnes_task_public_update(path)
        if path.startswith("/api/admin/products/"):
            return self.handle_admin_products_update(path)
        if path.startswith("/api/admin/agnes-keys/"):
            return self.handle_admin_agnes_keys_update(path)
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/agnes/tasks/"):
            return self.handle_agnes_task_delete(path)
        if path.startswith("/api/admin/products/"):
            return self.handle_admin_products_delete(path)
        if path.startswith("/api/admin/agnes-keys/"):
            return self.handle_admin_agnes_keys_delete(path)
        self.send_error(HTTPStatus.NOT_FOUND)

    def serve_static(self, path: str):
        if path == "/":
            rel = "index.html"
        elif path == "/admin":
            rel = "admin.html"
        elif path == "/admin/model-control":
            rel = "admin-model-control.html"
        elif path == "/admin/bigscreen":
            rel = "admin-bigscreen.html"
        elif path == "/admin/login":
            rel = "admin-login.html"
        elif path == "/admin/register":
            rel = "admin-register.html"
        elif path == "/login":
            rel = "user-login.html"
        elif path == "/account":
            rel = "account.html"
        elif path == "/agnes-chat":
            rel = "agnes-chat.html"
        elif path == "/agnes-video-v2":
            rel = "agnes-video-v2.html"
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
        self.end_headers()
        self.wfile.write(data)

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

    def parse_cookies(self):
        raw = self.headers.get("Cookie", "")
        cookies = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v
        return cookies

    def get_session(self):
        cookies = self.parse_cookies()
        token = cookies.get(ADMIN_SESSION_COOKIE)
        if not token:
            return None
        sess = SESSIONS.get(token)
        if not sess:
            return None
        if sess["exp"] < time.time():
            SESSIONS.pop(token, None)
            return None
        return token, sess

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

    def create_product_version_snapshot(self, product_id: int, created_by: str, source: str = "snapshot"):
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if not row:
                return None
            cur = conn.execute(
                """
                INSERT INTO product_versions (
                    product_id, name, slug, category, tags, announcement, version, summary, description, changelog, status,
                    file_name, file_path, file_size, file_sha256, published_at, created_at, created_by, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["name"],
                    row["slug"],
                    row["category"],
                    row["tags"],
                    row["announcement"],
                    row["version"],
                    row["summary"],
                    row["description"],
                    row["changelog"],
                    row["status"],
                    row["file_name"],
                    row["file_path"],
                    row["file_size"],
                    row["file_sha256"],
                    row["published_at"],
                    now_iso(),
                    created_by,
                    source,
                ),
            )
            conn.commit()
            vid = cur.lastrowid
            return conn.execute("SELECT * FROM product_versions WHERE id = ?", (vid,)).fetchone()
        finally:
            conn.close()

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
        return token, sess

    def require_user_auth(self):
        sess = self.get_user_session()
        if not sess:
            self.send_json({"error": "user login required"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        return sess

    def get_agnes_session(self):
        # Prefer explicit user session when both cookies exist.
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

    def mask_api_key(self, api_key: str) -> str:
        if not api_key:
            return ""
        if len(api_key) <= 8:
            return "*" * len(api_key)
        return f"{api_key[:4]}...{api_key[-4:]}"

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

    def json_safe_value(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, bytes):
            return value.hex()
        return str(value)

    def dashboard_mask_value(self, column_name: str, value):
        if column_name not in DASHBOARD_MASKED_COLUMNS:
            return self.json_safe_value(value)
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
                "default": self.json_safe_value(row["dflt_value"]),
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
                    "status": self.json_safe_value(row["status"]),
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

    def handle_admin_dashboard_get(self):
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
                "masked_key": self.mask_api_key(current_key["api_key"] or ""),
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
                    "started_at": datetime.fromtimestamp(
                        float(SERVER_RUNTIME["started_at"]), timezone.utc
                    ).isoformat(),
                    "uptime_seconds": max(0, int(now_ts - float(SERVER_RUNTIME["started_at"]))),
                    "host": SERVER_RUNTIME["bound_host"] or os.getenv("HOST", "127.0.0.1"),
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

    def estimate_text_tokens(self, text: str) -> int:
        return estimate_text_tokens_value(text)

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
        content: str,
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
            SELECT *
            FROM agnes_chat_model_config
            WHERE id = 1
            LIMIT 1
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
        for key in (
            "default_model",
            "default_system_prompt",
            "updated_at",
            "updated_by",
        ):
            payload[key] = row[key] or payload[key]
        for key in (
            "default_temperature",
            "default_max_tokens",
            "context_window_messages",
            "thinking_context_window_messages",
            "summary_max_lines",
            "summary_max_chars",
            "thinking_summary_max_chars",
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
        data["default_temperature"] = clamp_float_value(
            body.get("default_temperature"),
            0.0,
            2.0,
            float(defaults["default_temperature"]),
        )
        data["default_max_tokens"] = clamp_int_value(
            body.get("default_max_tokens"),
            128,
            65535,
            int(defaults["default_max_tokens"]),
        )
        data["default_enable_thinking"] = bool(
            defaults["default_enable_thinking"] if "default_enable_thinking" not in body else body.get("default_enable_thinking")
        )
        data["context_window_messages"] = clamp_int_value(
            body.get("context_window_messages"),
            1,
            64,
            int(defaults["context_window_messages"]),
        )
        data["thinking_context_window_messages"] = clamp_int_value(
            body.get("thinking_context_window_messages"),
            1,
            64,
            int(defaults["thinking_context_window_messages"]),
        )
        data["summary_max_lines"] = clamp_int_value(
            body.get("summary_max_lines"),
            0,
            64,
            int(defaults["summary_max_lines"]),
        )
        data["summary_max_chars"] = clamp_int_value(
            body.get("summary_max_chars"),
            0,
            12000,
            int(defaults["summary_max_chars"]),
        )
        data["thinking_summary_max_chars"] = clamp_int_value(
            body.get("thinking_summary_max_chars"),
            0,
            12000,
            int(defaults["thinking_summary_max_chars"]),
        )
        data["retain_thinking_on_empty_content"] = bool(
            defaults["retain_thinking_on_empty_content"]
            if "retain_thinking_on_empty_content" not in body
            else body.get("retain_thinking_on_empty_content")
        )

        if data["thinking_context_window_messages"] > data["context_window_messages"]:
            data["thinking_context_window_messages"] = data["context_window_messages"]
        if data["thinking_summary_max_chars"] > data["summary_max_chars"] and data["summary_max_chars"] > 0:
            data["thinking_summary_max_chars"] = data["summary_max_chars"]

        return data, ""

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
            """
            SELECT 1 FROM agnes_video_requests
            WHERE user_id = ? AND status = 'pending'
            LIMIT 1
            """,
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

    def handle_agnes_tasks_get(self):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        owner = self.get_current_agnes_owner(auth_ctx)
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT id, task_id, owner_role, owner_name, model, prompt, status, progress, video_url, seconds, is_public, public_at, last_error, created_at, updated_at
                FROM agnes_video_tasks
                WHERE owner_key = ?
                ORDER BY updated_at DESC
                LIMIT 100
                """,
                (owner["owner_key"],),
            ).fetchall()
        finally:
            conn.close()
        items = [
            {
                "id": r["id"],
                "task_id": r["task_id"],
                "owner_role": r["owner_role"] or "guest",
                "owner_name": r["owner_name"] or "guest",
                "model": r["model"] or "",
                "prompt": r["prompt"] or "",
                "status": r["status"] or "",
                "progress": int(r["progress"] or 0),
                "video_url": r["video_url"] or "",
                "seconds": r["seconds"] or "",
                "is_public": bool(int(r["is_public"] or 0)),
                "public_at": r["public_at"] or None,
                "last_error": r["last_error"] or "",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
        self.send_json({"owner": owner, "items": items})

    def handle_agnes_public_videos_get(self):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        parsed = urlparse(self.path)
        limit = 80
        query = parsed.query or ""
        for pair in query.split("&"):
            if pair.startswith("limit="):
                raw = (pair.split("=", 1)[1] or "").strip()
                try:
                    limit = int(raw)
                except ValueError:
                    limit = 80
        limit = max(1, min(200, limit))

        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT task_id, owner_role, owner_name, prompt, video_url, seconds, status, progress, public_at, updated_at
                FROM agnes_video_tasks
                WHERE is_public = 1
                  AND status = 'completed'
                  AND TRIM(COALESCE(video_url, '')) != ''
                ORDER BY COALESCE(public_at, updated_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        items = [
            {
                "task_id": r["task_id"] or "",
                "owner_role": r["owner_role"] or "",
                "owner_name": r["owner_name"] or "",
                "prompt": r["prompt"] or "",
                "video_url": r["video_url"] or "",
                "seconds": r["seconds"] or "",
                "status": r["status"] or "",
                "progress": int(r["progress"] or 0),
                "public_at": r["public_at"] or None,
                "updated_at": r["updated_at"] or None,
            }
            for r in rows
        ]
        self.send_json({"items": items})

    def handle_agnes_quota_get(self):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        if auth_ctx.get("role") == "admin":
            return self.send_json(
                {
                    "is_admin": True,
                    "free_limit": AGNES_FREE_VIDEO_LIMIT,
                    "used_count": 0,
                    "remaining_free": AGNES_FREE_VIDEO_LIMIT,
                    "approved_unused_count": 0,
                    "has_pending_request": False,
                    "can_create_now": True,
                    "rule": "admin-unlimited",
                }
            )
        user_id = int(auth_ctx.get("user_id") or 0)

        conn = get_db()
        try:
            quota = self.get_agnes_video_quota_summary(conn, user_id)
        finally:
            conn.close()
        self.send_json(quota)

    def handle_agnes_video_request_create(self):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        if auth_ctx.get("role") == "admin":
            return self.send_json(
                {"error": "admin-unlimited-no-request-required"},
                status=HTTPStatus.BAD_REQUEST,
            )
        user_id = int(auth_ctx.get("user_id") or 0)
        owner = self.get_current_agnes_owner(auth_ctx)

        try:
            body = self.read_json_body()
        except Exception:
            body = {}
        reason = str(body.get("reason") or "").strip()[:1000]

        conn = get_db()
        try:
            quota = self.get_agnes_video_quota_summary(conn, user_id)
            if quota["remaining_free"] > 0:
                return self.send_json(
                    {"error": "free quota still available", "quota": quota},
                    status=HTTPStatus.BAD_REQUEST,
                )
            if quota["approved_unused_count"] > 0:
                return self.send_json(
                    {"error": "approved quota already available", "quota": quota},
                    status=HTTPStatus.BAD_REQUEST,
                )
            pending = conn.execute(
                "SELECT id FROM agnes_video_requests WHERE user_id = ? AND status = 'pending' LIMIT 1",
                (user_id,),
            ).fetchone()
            if pending:
                return self.send_json(
                    {"error": "request already pending", "request_id": int(pending["id"]), "quota": quota},
                    status=HTTPStatus.CONFLICT,
                )
            cur = conn.execute(
                """
                INSERT INTO agnes_video_requests (user_id, owner_key, reason, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (user_id, owner.get("owner_key", ""), reason, now_iso()),
            )
            conn.commit()
            req_id = int(cur.lastrowid)
            quota = self.get_agnes_video_quota_summary(conn, user_id)
        finally:
            conn.close()
        self.send_json({"ok": True, "request_id": req_id, "quota": quota})

    def handle_agnes_chat_sessions_get(self):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        owner = self.get_current_agnes_owner(auth_ctx)
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM agnes_chat_sessions
                WHERE owner_key = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (owner["owner_key"],),
            ).fetchall()
            items = [self.serialize_chat_session(conn, row) for row in rows]
        finally:
            conn.close()
        self.send_json({"items": items})

    def handle_agnes_chat_sessions_create(self):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        try:
            body = self.read_json_body()
        except Exception:
            body = {}
        owner = self.get_current_agnes_owner(auth_ctx)
        title = normalize_chat_session_title(body.get("title") or "")
        conn = get_db()
        try:
            row = self.create_chat_session_record(conn, owner, auth_ctx, title, body if isinstance(body, dict) else {})
            conn.commit()
            item = self.serialize_chat_session(conn, row)
        finally:
            conn.close()
        self.send_json({"ok": True, "item": item}, status=HTTPStatus.CREATED)

    def handle_agnes_runtime_get(self):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        owner = self.get_current_agnes_owner(auth_ctx)
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, label, api_key, enabled FROM agnes_api_keys WHERE enabled = 1 ORDER BY id ASC"
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return self.send_json(
                {
                    "base_url": "/api/agnes",
                    "viewer": owner,
                    "has_enabled_key": False,
                    "rotation": None,
                }
            )

        with AGNES_KEY_ROTATION_LOCK:
            idx = AGNES_KEY_ROTATION_CURSOR % len(rows)

        row = rows[idx]
        self.send_json(
            {
                "base_url": "/api/agnes",
                "viewer": owner,
                "has_enabled_key": True,
                "rotation": {
                    "current_index": idx + 1,
                    "total": len(rows),
                    "key_id": int(row["id"]),
                    "label": row["label"] or "",
                    "masked_key": self.mask_api_key(row["api_key"] or ""),
                },
            }
        )

    def handle_agnes_task_delete(self, path: str):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        prefix = "/api/agnes/tasks/"
        task_id = unquote(path[len(prefix):]) if path.startswith(prefix) else ""
        task_id = (task_id or "").strip()
        if not task_id or "/" in task_id:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        owner = self.get_current_agnes_owner(auth_ctx)
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id FROM agnes_video_tasks WHERE task_id = ? AND owner_key = ? LIMIT 1",
                (task_id, owner["owner_key"]),
            ).fetchone()
            if not row:
                return self.send_json({"error": "task not found"}, status=HTTPStatus.NOT_FOUND)
            conn.execute("DELETE FROM agnes_video_tasks WHERE id = ?", (row["id"],))
            conn.commit()
        finally:
            conn.close()
        self.send_json({"ok": True, "task_id": task_id})

    def handle_agnes_task_public_update(self, path: str):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        prefix = "/api/agnes/tasks/"
        suffix = "/public"
        if not (path.startswith(prefix) and path.endswith(suffix)):
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        task_id = unquote(path[len(prefix):-len(suffix)]).strip()
        if not task_id or "/" in task_id:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            body = self.read_json_body()
        except Exception:
            body = {}
        is_public = bool(body.get("is_public"))
        owner = self.get_current_agnes_owner(auth_ctx)

        conn = get_db()
        try:
            row = conn.execute(
                """
                SELECT id, status, video_url, is_public, public_at
                FROM agnes_video_tasks
                WHERE task_id = ? AND owner_key = ?
                LIMIT 1
                """,
                (task_id, owner["owner_key"]),
            ).fetchone()
            if not row:
                return self.send_json({"error": "task not found"}, status=HTTPStatus.NOT_FOUND)
            if is_public and (
                str(row["status"] or "").strip().lower() != "completed"
                or not str(row["video_url"] or "").strip()
            ):
                return self.send_json(
                    {"error": "only completed task with video can be public"},
                    status=HTTPStatus.BAD_REQUEST,
                )
            now = now_iso()
            if is_public:
                conn.execute(
                    "UPDATE agnes_video_tasks SET is_public = 1, public_at = COALESCE(public_at, ?), updated_at = ? WHERE id = ?",
                    (now, now, int(row["id"])),
                )
            else:
                conn.execute(
                    "UPDATE agnes_video_tasks SET is_public = 0, public_at = NULL, updated_at = ? WHERE id = ?",
                    (now, int(row["id"])),
                )
            conn.commit()
        finally:
            conn.close()
        self.send_json({"ok": True, "task_id": task_id, "is_public": is_public})

    def call_agnes_upstream(self, method: str, api_path: str, api_key: str, payload=None):
        base_url = "https://apihub.agnes-ai.com/v1"
        url = f"{base_url}{api_path}"
        body = None
        headers = {"Authorization": f"Bearer {api_key}"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url=url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=180) as resp:
                status = int(getattr(resp, "status", HTTPStatus.OK))
                raw = resp.read()
                ctype = (resp.headers.get("Content-Type") or "").lower()
        except HTTPError as exc:
            status = int(exc.code)
            raw = exc.read()
            ctype = (exc.headers.get("Content-Type") or "").lower()
        except URLError as exc:
            return None, {"error": "upstream unavailable", "detail": str(exc.reason)}
        except Exception as exc:
            return None, {"error": "upstream request failed", "detail": str(exc)}

        if not raw:
            return status, {}
        text = raw.decode("utf-8", errors="replace")
        if "application/json" in ctype:
            try:
                return status, json.loads(text)
            except Exception:
                return status, {"raw": text}
        return status, {"raw": text}

    def call_agnes_chat_upstream(self, payload, api_key: str = ""):
        resolved_api_key = (api_key or AGNES_CHAT_API_KEY).strip()
        if not resolved_api_key:
            return None, {"error": "agnes chat api key not configured"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {resolved_api_key}",
            "Content-Type": "application/json",
        }
        req = Request(
            url=f"{AGNES_CHAT_API_BASE}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(req, timeout=180) as resp:
                status = int(getattr(resp, "status", HTTPStatus.OK))
                raw = resp.read()
                ctype = (resp.headers.get("Content-Type") or "").lower()
        except HTTPError as exc:
            status = int(exc.code)
            raw = exc.read()
            ctype = (exc.headers.get("Content-Type") or "").lower()
        except URLError as exc:
            return None, {"error": "upstream unavailable", "detail": str(exc.reason)}
        except Exception as exc:
            return None, {"error": "upstream request failed", "detail": str(exc)}

        if not raw:
            return status, {}
        text = raw.decode("utf-8", errors="replace")
        if "application/json" in ctype:
            try:
                return status, json.loads(text)
            except Exception:
                return status, {"raw": text}
        return status, {"raw": text}

    def open_agnes_chat_upstream_stream(self, payload, api_key: str = ""):
        resolved_api_key = (api_key or AGNES_CHAT_API_KEY).strip()
        if not resolved_api_key:
            return None, None, None, {"error": "agnes chat api key not configured"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {resolved_api_key}",
            "Content-Type": "application/json",
        }
        req = Request(
            url=f"{AGNES_CHAT_API_BASE}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            resp = urlopen(req, timeout=180)
            status = int(getattr(resp, "status", HTTPStatus.OK))
            ctype = (resp.headers.get("Content-Type") or "").lower()
            return status, ctype, resp, None
        except HTTPError as exc:
            status = int(exc.code)
            raw = exc.read()
            ctype = (exc.headers.get("Content-Type") or "").lower()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            if "application/json" in ctype and text:
                try:
                    return status, ctype, None, json.loads(text)
                except Exception:
                    return status, ctype, None, {"raw": text}
            return status, ctype, None, {"raw": text} if text else {}
        except URLError as exc:
            return None, None, None, {"error": "upstream unavailable", "detail": str(exc.reason)}
        except Exception as exc:
            return None, None, None, {"error": "upstream request failed", "detail": str(exc)}

    def parse_chat_sse_block(self, block_text: str):
        lines = [line for line in str(block_text or "").splitlines() if line.startswith("data:")]
        if not lines:
            return None
        data_text = "\n".join(line[5:].lstrip() for line in lines).strip()
        if not data_text:
            return None
        if data_text == "[DONE]":
            return {"done": True, "content": "", "thinking": "", "usage": None, "error": ""}
        try:
            payload = json.loads(data_text)
        except Exception:
            return None
        choice = ((payload.get("choices") or [{}])[0]) if isinstance(payload, dict) else {}
        delta = choice.get("delta") if isinstance(choice, dict) else {}
        message = choice.get("message") if isinstance(choice, dict) else {}
        content = ""
        if isinstance(delta, dict):
            content = str(delta.get("content") or "")
        if not content and isinstance(message, dict):
            content = str(message.get("content") or "")
        thinking = ""
        for src in (delta if isinstance(delta, dict) else {}, message if isinstance(message, dict) else {}, choice, payload):
            if not isinstance(src, dict):
                continue
            thinking = str(
                src.get("reasoning_content")
                or src.get("reasoning")
                or src.get("thinking")
                or src.get("reasoning_text")
                or ""
            ).strip()
            if thinking:
                break
        error_text = ""
        if isinstance(payload, dict):
            if isinstance(payload.get("error"), str):
                error_text = payload.get("error") or ""
            elif isinstance(payload.get("error"), dict):
                error_text = str(payload.get("error", {}).get("message") or "")
        return {
            "done": False,
            "content": content,
            "thinking": thinking,
            "usage": payload.get("usage") if isinstance(payload, dict) else None,
            "error": error_text,
        }

    def handle_agnes_chat_create(self):
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        if not isinstance(body, dict):
            return self.send_json({"error": "invalid payload"}, status=HTTPStatus.BAD_REQUEST)

        auth_ctx = self.get_agnes_session()
        if not auth_ctx:
            return self.send_json({"error": "login required"}, status=HTTPStatus.UNAUTHORIZED)

        effective_config = self.get_effective_chat_model_config()
        model = (body.get("model") or "").strip() or str(effective_config.get("default_model") or "agnes-2.0-flash")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return self.send_json({"error": "messages required"}, status=HTTPStatus.BAD_REQUEST)

        cleaned_messages = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = item.get("content")
            if role not in {"system", "user", "assistant"}:
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            cleaned_messages.append({"role": role, "content": content})
        if not cleaned_messages:
            return self.send_json({"error": "messages required"}, status=HTTPStatus.BAD_REQUEST)

        stream = bool(body.get("stream", True))
        async_mode = bool(body.get("async"))
        owner = self.get_current_agnes_owner(auth_ctx) if auth_ctx else None
        latest_user_message = next(
            (item for item in reversed(cleaned_messages) if item.get("role") == "user" and str(item.get("content") or "").strip()),
            None,
        )
        session_id = body.get("session_id")
        try:
            session_id = int(session_id) if session_id is not None and str(session_id).strip() else None
        except (TypeError, ValueError):
            return self.send_json({"error": "invalid session_id"}, status=HTTPStatus.BAD_REQUEST)
        enable_thinking = bool(effective_config.get("default_enable_thinking"))
        if "enable_thinking" in body:
            enable_thinking = bool(body.get("enable_thinking"))
        elif isinstance(body.get("chat_template_kwargs"), dict):
            enable_thinking = bool(body.get("chat_template_kwargs", {}).get("enable_thinking"))
        session_title = normalize_chat_session_title(
            body.get("session_title") or body.get("title") or (latest_user_message or {}).get("content") or ""
        )
        resolved_system_prompt = str(
            body.get("system_prompt")
            or body.get("systemPrompt")
            or effective_config.get("default_system_prompt")
            or ""
        )
        session_meta = {
            "model": model,
            "system_prompt": resolved_system_prompt,
            "enable_thinking": enable_thinking,
        }
        persisted_session_id = None
        persisted_user_message_id = None

        if auth_ctx:
            conn = get_db()
            try:
                if session_id:
                    session_row = self.get_chat_session_row_for_owner(conn, session_id, owner["owner_key"])
                    if not session_row:
                        return self.send_json({"error": "session not found"}, status=HTTPStatus.NOT_FOUND)
                    self.update_chat_session_record(conn, session_row, session_title, session_meta)
                    session_row = self.get_chat_session_row_for_owner(conn, session_id, owner["owner_key"])
                else:
                    session_row = self.create_chat_session_record(conn, owner, auth_ctx, session_title, session_meta)
                    session_id = int(session_row["id"])
                if latest_user_message:
                    persisted_user_message_id = self.create_chat_message_record(
                        conn,
                        int(session_row["id"]),
                        "user",
                        str(latest_user_message.get("content") or ""),
                    )
                conn.commit()
                persisted_session_id = int(session_row["id"])
            finally:
                conn.close()

        payload = {
            "model": model,
            "messages": cleaned_messages,
            "stream": stream,
        }

        if "temperature" in body:
            try:
                payload["temperature"] = float(body.get("temperature"))
            except (TypeError, ValueError):
                return self.send_json({"error": "invalid temperature"}, status=HTTPStatus.BAD_REQUEST)
        else:
            payload["temperature"] = float(effective_config.get("default_temperature") or 0.7)
        if "top_p" in body:
            try:
                payload["top_p"] = float(body.get("top_p"))
            except (TypeError, ValueError):
                return self.send_json({"error": "invalid top_p"}, status=HTTPStatus.BAD_REQUEST)
        if "max_tokens" in body:
            try:
                payload["max_tokens"] = int(body.get("max_tokens"))
            except (TypeError, ValueError):
                return self.send_json({"error": "invalid max_tokens"}, status=HTTPStatus.BAD_REQUEST)
        else:
            payload["max_tokens"] = int(effective_config.get("default_max_tokens") or 2048)
        if "chat_template_kwargs" in body and isinstance(body.get("chat_template_kwargs"), dict):
            payload["chat_template_kwargs"] = body.get("chat_template_kwargs")
        elif enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        if "tools" in body and isinstance(body.get("tools"), list):
            payload["tools"] = body.get("tools")
        if "tool_choice" in body:
            payload["tool_choice"] = body.get("tool_choice")

        if async_mode:
            if not auth_ctx or not persisted_session_id or not persisted_user_message_id:
                return self.send_json({"error": "async chat requires persisted session"}, status=HTTPStatus.BAD_REQUEST)
            task_id = generate_chat_task_id()
            assistant_message_id = None
            conn = get_db()
            try:
                begin_immediate_with_retry(conn)
                assistant_message_id = self.create_chat_message_record(
                    conn,
                    int(persisted_session_id),
                    "assistant",
                    "",
                    "",
                    token_source="",
                    task_id=task_id,
                    status="queued",
                )
                queued_payload = dict(payload)
                queued_payload["stream"] = True
                self.create_chat_task_record(
                    conn,
                    task_id,
                    int(persisted_session_id),
                    int(persisted_user_message_id),
                    int(assistant_message_id),
                    owner,
                    auth_ctx,
                    model,
                    queued_payload,
                )
                conn.commit()
                assistant_row = conn.execute(
                    "SELECT * FROM agnes_chat_messages WHERE id = ? LIMIT 1",
                    (int(assistant_message_id),),
                ).fetchone()
            finally:
                conn.close()
            return self.send_json(
                {
                    "ok": True,
                    "async": True,
                    "task_id": task_id,
                    "session_id": int(persisted_session_id),
                    "assistant_message": self.serialize_chat_message(assistant_row) if assistant_row else None,
                },
                status=HTTPStatus.ACCEPTED,
            )

        selected_key_id = None
        conn = get_db()
        try:
            selected_key_id, api_key = pick_agnes_chat_api_key_raw(conn)
        finally:
            conn.close()
        if not api_key:
            return self.send_json(
                {"error": "agnes chat api key not configured"},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        if not stream:
            status, resp_payload = self.call_agnes_chat_upstream(payload, api_key=api_key)
            if status is None:
                return self.send_json(resp_payload, status=HTTPStatus.BAD_GATEWAY)
            if selected_key_id is not None:
                conn = get_db()
                try:
                    conn.execute(
                        "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                        (now_iso(), selected_key_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            if auth_ctx and persisted_session_id and isinstance(resp_payload, dict):
                usage = resp_payload.get("usage") if isinstance(resp_payload, dict) else {}
                choice = ((resp_payload.get("choices") or [{}])[0]) if isinstance(resp_payload, dict) else {}
                message = choice.get("message") if isinstance(choice, dict) else {}
                assistant_content = str((message or {}).get("content") or "")
                assistant_thinking = (
                    extract_chat_reasoning_text(message)
                    or extract_chat_reasoning_text(choice)
                    or extract_chat_reasoning_text(resp_payload)
                )
                if assistant_content.strip() or assistant_thinking.strip():
                    conn = get_db()
                    try:
                        self.create_chat_message_record(
                            conn,
                            persisted_session_id,
                            "assistant",
                            assistant_content,
                            assistant_thinking,
                            prompt_tokens=int((usage or {}).get("prompt_tokens") or 0),
                            completion_tokens=int((usage or {}).get("completion_tokens") or 0),
                            total_tokens=int((usage or {}).get("total_tokens") or 0),
                            token_source="upstream" if usage else "",
                        )
                        conn.commit()
                    finally:
                        conn.close()
            return self.send_json(resp_payload, status=status)

        status, ctype, upstream_resp, err_payload = self.open_agnes_chat_upstream_stream(payload, api_key=api_key)
        if status is None:
            return self.send_json(err_payload, status=HTTPStatus.BAD_GATEWAY)
        if upstream_resp is None:
            return self.send_json(err_payload, status=status)

        try:
            if selected_key_id is not None:
                conn = get_db()
                try:
                    conn.execute(
                        "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                        (now_iso(), selected_key_id),
                    )
                    conn.commit()
                finally:
                    conn.close()

            if "text/event-stream" in (ctype or ""):
                self.send_sse_headers(status=status)
                sse_buffer = ""
                assistant_content = ""
                assistant_thinking = ""
                usage = None
                while True:
                    chunk = upstream_resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    sse_buffer += chunk.decode("utf-8", errors="replace")
                    blocks = sse_buffer.split("\n\n")
                    sse_buffer = blocks.pop() or ""
                    for block in blocks:
                        parsed_block = self.parse_chat_sse_block(block)
                        if not parsed_block:
                            continue
                        if parsed_block.get("content"):
                            assistant_content = merge_stream_text(assistant_content, parsed_block.get("content") or "")
                        if parsed_block.get("thinking"):
                            assistant_thinking = merge_stream_text(assistant_thinking, parsed_block.get("thinking") or "")
                        if parsed_block.get("usage"):
                            usage = parsed_block.get("usage")
                if sse_buffer.strip():
                    parsed_block = self.parse_chat_sse_block(sse_buffer)
                    if parsed_block:
                        if parsed_block.get("content"):
                            assistant_content = merge_stream_text(assistant_content, parsed_block.get("content") or "")
                        if parsed_block.get("thinking"):
                            assistant_thinking = merge_stream_text(assistant_thinking, parsed_block.get("thinking") or "")
                        if parsed_block.get("usage"):
                            usage = parsed_block.get("usage")
                if auth_ctx and persisted_session_id and (assistant_content.strip() or assistant_thinking.strip()):
                    conn = get_db()
                    try:
                        self.create_chat_message_record(
                            conn,
                            persisted_session_id,
                            "assistant",
                            assistant_content,
                            assistant_thinking,
                            prompt_tokens=int((usage or {}).get("prompt_tokens") or 0),
                            completion_tokens=int((usage or {}).get("completion_tokens") or 0),
                            total_tokens=int((usage or {}).get("total_tokens") or 0),
                            token_source="upstream" if usage else "",
                        )
                        conn.commit()
                    finally:
                        conn.close()
                return

            raw = upstream_resp.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            parsed = {}
            if text:
                if "application/json" in (ctype or ""):
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = {"raw": text}
                else:
                    parsed = {"raw": text}

            self.send_sse_headers(status=status)
            content = ""
            thinking = ""
            if isinstance(parsed, dict):
                message = parsed.get("choices", [{}])[0].get("message", {}) or {}
                content = str(message.get("content") or "")
                thinking = extract_chat_reasoning_text(message) or extract_chat_reasoning_text(parsed)
            if thinking:
                self.write_sse_data(
                    {
                        "choices": [
                            {
                                "delta": {"reasoning_content": thinking},
                                "index": 0,
                            }
                        ]
                    }
                )
            if content:
                self.write_sse_data(
                    {
                        "choices": [
                            {
                                "delta": {"content": content},
                                "index": 0,
                            }
                        ]
                    }
                )
            self.write_sse_data(
                {
                    "choices": [
                        {
                            "delta": {},
                            "index": 0,
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": parsed.get("usage", {}) if isinstance(parsed, dict) else {},
                }
            )
            self.write_sse_data("[DONE]")
            if auth_ctx and persisted_session_id and (content.strip() or thinking.strip()):
                usage = parsed.get("usage", {}) if isinstance(parsed, dict) else {}
                conn = get_db()
                try:
                    self.create_chat_message_record(
                        conn,
                        persisted_session_id,
                        "assistant",
                        content,
                        thinking,
                        prompt_tokens=int((usage or {}).get("prompt_tokens") or 0),
                        completion_tokens=int((usage or {}).get("completion_tokens") or 0),
                        total_tokens=int((usage or {}).get("total_tokens") or 0),
                        token_source="upstream" if usage else "",
                    )
                    conn.commit()
                finally:
                    conn.close()
            return
        finally:
            upstream_resp.close()

    def handle_admin_chat_model_config_get(self):
        admin_data = self.require_level2_auth()
        if not admin_data:
            return
        conn = get_db()
        try:
            config = self.get_effective_chat_model_config(conn)
        finally:
            conn.close()
        self.send_json(
            {
                "item": config,
                "viewer": {
                    "username": admin_data.get("username", ""),
                    "admin_level": int(admin_data.get("admin_level", 1)),
                    "is_super": bool(admin_data.get("is_super")),
                },
            }
        )

    def handle_admin_chat_model_config_update(self):
        admin_data = self.require_level2_auth()
        if not admin_data:
            return
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        config_data, error_text = self.validate_chat_model_config_payload(body)
        if error_text:
            return self.send_json({"error": error_text}, status=HTTPStatus.BAD_REQUEST)

        now = now_iso()
        conn = get_db()
        try:
            conn.execute(
                """
                UPDATE agnes_chat_model_config
                SET default_model = ?,
                    default_system_prompt = ?,
                    default_temperature = ?,
                    default_max_tokens = ?,
                    default_enable_thinking = ?,
                    context_window_messages = ?,
                    thinking_context_window_messages = ?,
                    summary_max_lines = ?,
                    summary_max_chars = ?,
                    thinking_summary_max_chars = ?,
                    retain_thinking_on_empty_content = ?,
                    updated_at = ?,
                    updated_by = ?
                WHERE id = 1
                """,
                (
                    config_data["default_model"],
                    config_data["default_system_prompt"],
                    float(config_data["default_temperature"]),
                    int(config_data["default_max_tokens"]),
                    1 if config_data["default_enable_thinking"] else 0,
                    int(config_data["context_window_messages"]),
                    int(config_data["thinking_context_window_messages"]),
                    int(config_data["summary_max_lines"]),
                    int(config_data["summary_max_chars"]),
                    int(config_data["thinking_summary_max_chars"]),
                    1 if config_data["retain_thinking_on_empty_content"] else 0,
                    now,
                    str(admin_data.get("username") or ""),
                ),
            )
            conn.commit()
            config = self.get_effective_chat_model_config(conn)
        finally:
            conn.close()
        self.send_json({"ok": True, "item": config})

    def handle_agnes_chat_config_get(self):
        conn = get_db()
        try:
            config = self.get_effective_chat_model_config(conn)
        finally:
            conn.close()
        self.send_json(
            {
                "item": config,
                "login_required": True,
                "proxy_endpoint": "/api/agnes/chat",
            }
        )

    def handle_admin_agnes_keys_get(self):
        admin_data = self.require_level2_auth()
        if not admin_data:
            return
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT id, label, api_key, enabled, created_by, created_at, updated_at, last_used_at, use_count
                FROM agnes_api_keys
                ORDER BY id ASC
                """
            ).fetchall()
        finally:
            conn.close()
        items = [
            {
                "id": r["id"],
                "label": r["label"] or "",
                "enabled": bool(r["enabled"]),
                "masked_key": self.mask_api_key(r["api_key"] or ""),
                "created_by": r["created_by"] or "",
                "created_at": r["created_at"] or None,
                "updated_at": r["updated_at"] or None,
                "last_used_at": r["last_used_at"] or None,
                "use_count": int(r["use_count"] or 0),
            }
            for r in rows
        ]
        self.send_json({"items": items})

    def handle_admin_agnes_keys_create(self):
        admin_data = self.require_level2_auth()
        if not admin_data:
            return
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        api_key = (body.get("api_key") or "").strip()
        label = (body.get("label") or "").strip()
        enabled = 1 if bool(body.get("enabled", True)) else 0
        if not api_key:
            return self.send_json({"error": "api_key required"}, status=HTTPStatus.BAD_REQUEST)

        now = now_iso()
        conn = get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO agnes_api_keys (label, api_key, enabled, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (label, api_key, enabled, admin_data.get("username", ""), now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM agnes_api_keys WHERE id = ?", (cur.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            return self.send_json({"error": "api_key already exists"}, status=HTTPStatus.CONFLICT)
        finally:
            conn.close()
        self.send_json(
            {
                "id": row["id"],
                "label": row["label"] or "",
                "enabled": bool(row["enabled"]),
                "masked_key": self.mask_api_key(row["api_key"] or ""),
                "created_by": row["created_by"] or "",
                "created_at": row["created_at"] or None,
                "updated_at": row["updated_at"] or None,
                "last_used_at": row["last_used_at"] or None,
                "use_count": int(row["use_count"] or 0),
            },
            status=HTTPStatus.CREATED,
        )

    def handle_admin_agnes_keys_update(self, path: str):
        admin_data = self.require_level2_auth()
        if not admin_data:
            return
        key_id = self.parse_path_int_id(path, "/api/admin/agnes-keys/")
        if not key_id:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        fields = []
        params = []
        if "label" in body:
            fields.append("label = ?")
            params.append((body.get("label") or "").strip())
        if "enabled" in body:
            fields.append("enabled = ?")
            params.append(1 if bool(body.get("enabled")) else 0)
        if "api_key" in body:
            new_key = (body.get("api_key") or "").strip()
            if not new_key:
                return self.send_json({"error": "api_key cannot be empty"}, status=HTTPStatus.BAD_REQUEST)
            fields.append("api_key = ?")
            params.append(new_key)
        if not fields:
            return self.send_json({"error": "no fields to update"}, status=HTTPStatus.BAD_REQUEST)
        fields.append("updated_at = ?")
        params.append(now_iso())
        params.append(key_id)

        conn = get_db()
        try:
            cur = conn.execute(
                f"UPDATE agnes_api_keys SET {', '.join(fields)} WHERE id = ?",
                tuple(params),
            )
            if cur.rowcount <= 0:
                return self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            conn.commit()
            row = conn.execute("SELECT * FROM agnes_api_keys WHERE id = ?", (key_id,)).fetchone()
        except sqlite3.IntegrityError:
            return self.send_json({"error": "api_key already exists"}, status=HTTPStatus.CONFLICT)
        finally:
            conn.close()

        self.send_json(
            {
                "id": row["id"],
                "label": row["label"] or "",
                "enabled": bool(row["enabled"]),
                "masked_key": self.mask_api_key(row["api_key"] or ""),
                "created_by": row["created_by"] or "",
                "created_at": row["created_at"] or None,
                "updated_at": row["updated_at"] or None,
                "last_used_at": row["last_used_at"] or None,
                "use_count": int(row["use_count"] or 0),
            }
        )

    def handle_admin_agnes_keys_delete(self, path: str):
        admin_data = self.require_level2_auth()
        if not admin_data:
            return
        key_id = self.parse_path_int_id(path, "/api/admin/agnes-keys/")
        if not key_id:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        conn = get_db()
        cur = None
        try:
            cur = conn.execute("DELETE FROM agnes_api_keys WHERE id = ?", (key_id,))
            conn.commit()
        finally:
            conn.close()
        if cur.rowcount <= 0:
            return self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        self.send_json({"ok": True})

    def handle_agnes_video_create(self):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        is_admin = auth_ctx.get("role") == "admin"
        user_id = int(auth_ctx.get("user_id") or 0) if not is_admin else 0
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        owner = self.get_current_agnes_owner(auth_ctx)
        conn = get_db()
        try:
            begin_immediate_with_retry(conn)
            approved_req = None
            if not is_admin:
                quota = self.get_agnes_video_quota_summary(conn, user_id)
                if not quota["can_create_now"]:
                    quota = self.get_agnes_video_quota_summary(conn, user_id)
                    return self.send_json(
                        {"error": "video quota exceeded", "quota": quota},
                        status=HTTPStatus.FORBIDDEN,
                    )
                if quota["remaining_free"] <= 0:
                    approved_req = conn.execute(
                        """
                        SELECT id FROM agnes_video_requests
                        WHERE user_id = ? AND status = 'approved' AND consumed_at IS NULL
                        ORDER BY reviewed_at DESC, id DESC
                        LIMIT 1
                        """,
                        (user_id,),
                    ).fetchone()
                    if approved_req is None:
                        quota = self.get_agnes_video_quota_summary(conn, user_id)
                        return self.send_json(
                            {"error": "video quota exceeded", "quota": quota},
                            status=HTTPStatus.FORBIDDEN,
                        )

            key_row = self.pick_agnes_api_key(conn)
            if not key_row:
                return self.send_json(
                    {"error": "no enabled agnes api key in pool"},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            status, payload = self.call_agnes_upstream("POST", "/videos", key_row["api_key"], body)
            if status is None:
                return self.send_json(payload, status=HTTPStatus.BAD_GATEWAY)
            if isinstance(payload, dict):
                task_id = str(payload.get("id") or "").strip()
                if task_id:
                    merged_payload = dict(payload)
                    if not merged_payload.get("model"):
                        merged_payload["model"] = body.get("model") or ""
                    if not merged_payload.get("prompt"):
                        merged_payload["prompt"] = body.get("prompt") or ""
                    self.upsert_agnes_task_binding(conn, task_id, int(key_row["id"]), owner, merged_payload)
                    if not is_admin:
                        req_id = int(approved_req["id"]) if approved_req else None
                        conn.execute(
                            """
                            INSERT INTO agnes_video_usage_events (user_id, owner_key, task_id, request_id, created_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (user_id, owner.get("owner_key", ""), task_id, req_id, now_iso()),
                        )
                        if approved_req:
                            conn.execute(
                                """
                                UPDATE agnes_video_requests
                                SET consumed_at = ?, consumed_task_id = ?
                                WHERE id = ?
                                """,
                                (now_iso(), task_id, int(approved_req["id"])),
                            )
            conn.execute(
                "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                (now_iso(), key_row["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        self.send_json(payload, status=status)

    def handle_agnes_video_get(self, path: str):
        auth_ctx = self.require_agnes_auth()
        if not auth_ctx:
            return
        prefix = "/api/agnes/videos/"
        task_id = unquote(path[len(prefix):]) if path.startswith(prefix) else ""
        task_id = (task_id or "").strip()
        if not task_id or "/" in task_id:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        owner = self.get_current_agnes_owner(auth_ctx)
        conn = get_db()
        try:
            local_row = conn.execute(
                "SELECT owner_key FROM agnes_video_tasks WHERE task_id = ? LIMIT 1",
                (task_id,),
            ).fetchone()
            if not local_row:
                return self.send_json({"error": "task not found"}, status=HTTPStatus.NOT_FOUND)
            if (local_row["owner_key"] or "") != owner["owner_key"]:
                return self.send_json({"error": "forbidden"}, status=HTTPStatus.FORBIDDEN)

            enabled_keys = self.list_enabled_agnes_keys(conn)
            if not enabled_keys:
                return self.send_json(
                    {"error": "no enabled agnes api key in pool"},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            tried_key_ids = set()
            chosen_row = None
            status = None
            payload = None

            bound_row = self.get_task_bound_key(conn, task_id)
            if bound_row and bound_row["api_key"]:
                chosen_row = bound_row
                tried_key_ids.add(int(bound_row["id"]))
                status, payload = self.call_agnes_upstream("GET", f"/videos/{task_id}", bound_row["api_key"])

            if status is None:
                # no bound key / bound key call transport failed
                pass
            elif not (status == HTTPStatus.BAD_REQUEST and self.is_task_not_exist_payload(payload)):
                # bound key works (or failed with non-task_not_exist), return directly
                conn.execute(
                    "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                    (now_iso(), chosen_row["id"]),
                )
                if isinstance(payload, dict):
                    self.upsert_agnes_task_binding(conn, task_id, int(chosen_row["id"]), owner, payload)
                conn.commit()
                return self.send_json(payload, status=status)

            # Fallback scan: when no binding, or binding stale / wrong.
            for row in enabled_keys:
                key_id = int(row["id"])
                if key_id in tried_key_ids:
                    continue
                s, p = self.call_agnes_upstream("GET", f"/videos/{task_id}", row["api_key"])
                if s is None:
                    continue
                # keep first response in case all are task_not_exist
                if status is None:
                    status, payload = s, p
                    chosen_row = row
                if s == HTTPStatus.BAD_REQUEST and self.is_task_not_exist_payload(p):
                    continue
                status, payload = s, p
                chosen_row = row
                break

            if status is None:
                return self.send_json({"error": "upstream unavailable"}, status=HTTPStatus.BAD_GATEWAY)

            if chosen_row:
                conn.execute(
                    "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                    (now_iso(), chosen_row["id"]),
                )
                if not (status == HTTPStatus.BAD_REQUEST and self.is_task_not_exist_payload(payload)):
                    if isinstance(payload, dict):
                        self.upsert_agnes_task_binding(conn, task_id, int(chosen_row["id"]), owner, payload)
            conn.commit()
        finally:
            conn.close()
        self.send_json(payload, status=status)

    def handle_admin_login(self):
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        username = (body.get("username") or "").strip()
        password = body.get("password") or ""

        session_user = None
        is_super = False
        admin_level = 1
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session_user = ADMIN_USERNAME
            is_super = True
            admin_level = 3
        else:
            conn = get_db()
            try:
                row = conn.execute(
                    "SELECT * FROM admin_accounts WHERE username = ?",
                    (username,),
                ).fetchone()
            finally:
                conn.close()
            if row and verify_password(password, row["password_hash"]):
                session_user = row["username"]
                is_super = bool(row["is_super"])
                admin_level = max(1, min(3, int(row["admin_level"] or 1)))
            else:
                return self.send_json({"error": "invalid credentials"}, status=HTTPStatus.UNAUTHORIZED)

        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {
            "username": session_user,
            "role": "admin",
            "is_super": is_super,
            "admin_level": admin_level,
            "exp": time.time() + SESSION_TTL_SECONDS,
        }

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
        data = json.dumps(
            {"ok": True, "username": session_user, "isSuper": is_super, "adminLevel": admin_level}
        ).encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_admin_logout(self):
        sess = self.get_session()
        if sess:
            token, _ = sess
            SESSIONS.pop(token, None)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}=deleted; Path=/; Max-Age=0; SameSite=Lax")
        data = json.dumps({"ok": True}).encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_user_login(self):
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        email = (body.get("email") or "").strip().lower()
        if not username or not password or not email:
            return self.send_json({"error": "username, password and email required"}, status=HTTPStatus.BAD_REQUEST)
        if not EMAIL_RE.match(email):
            return self.send_json({"error": "invalid email format"}, status=HTTPStatus.BAD_REQUEST)

        admin_user = None
        admin_level = 1
        is_super = False
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            admin_user = ADMIN_USERNAME
            admin_level = 3
            is_super = True
        else:
            conn = get_db()
            try:
                row = conn.execute(
                    "SELECT username, password_hash, is_super, admin_level FROM admin_accounts WHERE username = ?",
                    (username,),
                ).fetchone()
            finally:
                conn.close()
            if row and verify_password(password, row["password_hash"]):
                admin_user = row["username"]
                admin_level = max(1, min(3, int(row["admin_level"] or 1)))
                is_super = bool(row["is_super"])

        if admin_user:
            token = secrets.token_urlsafe(32)
            SESSIONS[token] = {
                "username": admin_user,
                "role": "admin",
                "is_super": is_super,
                "admin_level": admin_level,
                "exp": time.time() + SESSION_TTL_SECONDS,
            }

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
            data = json.dumps(
                {"ok": True, "role": "admin", "username": admin_user, "adminLevel": admin_level}
            ).encode("utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        conn = get_db()
        created = False
        try:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if row and row["password"] != password:
                return self.send_json({"error": "invalid credentials"}, status=HTTPStatus.UNAUTHORIZED)
            email_owner = conn.execute(
                "SELECT id, username FROM users WHERE email = ? LIMIT 1",
                (email,),
            ).fetchone()
            if not row:
                if email_owner:
                    return self.send_json({"error": "email already bound to another account"}, status=HTTPStatus.CONFLICT)
                conn.execute(
                    "INSERT INTO users (username, password, email, created_at) VALUES (?, ?, ?, ?)",
                    (username, password, email, now_iso()),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                created = True
            else:
                bound_email = (row["email"] or "").strip().lower()
                if bound_email and bound_email != email:
                    return self.send_json({"error": "email does not match this account"}, status=HTTPStatus.CONFLICT)
                if not bound_email:
                    if email_owner and int(email_owner["id"]) != int(row["id"]):
                        return self.send_json({"error": "email already bound to another account"}, status=HTTPStatus.CONFLICT)
                    conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, row["id"]))
                    conn.commit()
                    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        finally:
            conn.close()

        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {
            "role": "user",
            "user_id": row["id"],
            "username": row["username"],
            "exp": time.time() + SESSION_TTL_SECONDS,
        }

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", f"{USER_SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
        data = json.dumps(
            {
                "ok": True,
                "username": row["username"],
                "email": row["email"] if "email" in row.keys() else "",
                "created": created,
                "already_registered": (not created),
            }
        ).encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_user_logout(self):
        sess = self.get_user_session()
        if sess:
            token, _ = sess
            SESSIONS.pop(token, None)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", f"{USER_SESSION_COOKIE}=deleted; Path=/; Max-Age=0; SameSite=Lax")
        data = json.dumps({"ok": True}).encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_admin_me(self):
        sess = self.get_session()
        if not sess:
            return self.send_json({"loggedIn": False})
        _, data = sess
        upload_project_count = 0
        if not bool(data.get("is_super")):
            conn = get_db()
            try:
                upload_project_count = conn.execute(
                    "SELECT COUNT(*) FROM admin_upload_events WHERE admin_username = ?",
                    (data["username"],),
                ).fetchone()[0]
            finally:
                conn.close()
        self.send_json(
            {
                "loggedIn": True,
                "username": data["username"],
                "isSuper": bool(data.get("is_super")),
                "adminLevel": int(data.get("admin_level", 1)),
                "uploadProjectCount": upload_project_count,
                "autoPromoteTarget": LV1_AUTO_PROMOTE_PROJECT_COUNT,
            }
        )

    def handle_admin_register(self):
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        invite_token = (body.get("token") or "").strip()

        if not username or not password or not invite_token:
            return self.send_json(
                {"error": "username, password and token required"},
                status=HTTPStatus.BAD_REQUEST,
            )
        if len(username) < 3 or len(username) > 64:
            return self.send_json({"error": "username length must be 3-64"}, status=HTTPStatus.BAD_REQUEST)
        if len(password) < 6:
            return self.send_json({"error": "password too short"}, status=HTTPStatus.BAD_REQUEST)
        if username == ADMIN_USERNAME:
            return self.send_json({"error": "username reserved"}, status=HTTPStatus.CONFLICT)

        conn = get_db()
        try:
            begin_immediate_with_retry(conn)
            token_row = conn.execute(
                "SELECT * FROM admin_register_tokens WHERE token = ?",
                (invite_token,),
            ).fetchone()
            if not token_row:
                conn.rollback()
                return self.send_json({"error": "invalid token"}, status=HTTPStatus.BAD_REQUEST)
            if token_row["used_at"] is not None:
                conn.rollback()
                return self.send_json({"error": "token already used"}, status=HTTPStatus.CONFLICT)

            exists = conn.execute(
                "SELECT 1 FROM admin_accounts WHERE username = ? LIMIT 1",
                (username,),
            ).fetchone()
            if exists:
                conn.rollback()
                return self.send_json({"error": "username already exists"}, status=HTTPStatus.CONFLICT)

            cur = conn.execute(
                """
                INSERT INTO admin_accounts (username, password_hash, created_at, created_by, is_super, admin_level)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    username,
                    hash_password(password),
                    now_iso(),
                    token_row["created_by"],
                    max(1, min(3, int(token_row["admin_level"] or 1))),
                ),
            )
            admin_id = cur.lastrowid
            conn.execute(
                """
                UPDATE admin_register_tokens
                SET used_by_admin_id = ?, used_at = ?
                WHERE id = ?
                """,
                (admin_id, now_iso(), token_row["id"]),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return self.send_json({"error": "register failed"}, status=HTTPStatus.CONFLICT)
        finally:
            conn.close()

        self.send_json(
            {"ok": True, "username": username, "adminLevel": max(1, min(3, int(token_row["admin_level"] or 1)))},
            status=HTTPStatus.CREATED,
        )

    def handle_admin_tokens_create(self):
        admin = self.require_super_auth()
        if not admin:
            return
        try:
            body = self.read_json_body()
        except Exception:
            body = {}

        count = body.get("count", 1)
        level = body.get("level", 1)
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 1
        try:
            level = int(level)
        except (TypeError, ValueError):
            level = 1
        count = max(1, min(20, count))
        level = 3 if level == 3 else (2 if level == 2 else 1)

        creator = admin["username"]
        created_at = now_iso()
        created = []
        conn = get_db()
        try:
            for _ in range(count):
                token = f"KFA-{secrets.token_hex(8)}-{secrets.token_hex(8)}"
                conn.execute(
                    """
                    INSERT INTO admin_register_tokens (token, created_by, created_at, admin_level)
                    VALUES (?, ?, ?, ?)
                    """,
                    (token, creator, created_at, level),
                )
                created.append(token)
            conn.commit()
        finally:
            conn.close()

        self.send_json({"ok": True, "tokens": created, "count": len(created), "adminLevel": level})

    def handle_admin_tokens_get(self):
        admin = self.require_super_auth()
        if not admin:
            return
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT t.*, a.username AS used_by_username
                FROM admin_register_tokens t
                LEFT JOIN admin_accounts a ON a.id = t.used_by_admin_id
                ORDER BY t.id DESC
                LIMIT 200
                """
            ).fetchall()
            items = []
            for row in rows:
                items.append(
                    {
                        "id": row["id"],
                        "token": row["token"],
                        "created_by": row["created_by"],
                        "created_at": row["created_at"],
                        "admin_level": max(1, min(3, int(row["admin_level"] or 1))),
                        "used_at": row["used_at"],
                        "used_by_username": row["used_by_username"],
                        "status": "used" if row["used_at"] else "unused",
                    }
                )
        finally:
            conn.close()
        self.send_json({"items": items})

    def _publish_reviewer_scope(self, requester_level: int):
        if requester_level <= 1:
            return ("lv2plus", 2)
        if requester_level == 2:
            return ("lv3", 3)
        return ("none", 99)

    def _list_reviewer_usernames(self, min_level: int, exclude_username: str):
        users = []
        # Built-in super admin always acts as lv3 reviewer.
        if min_level <= 3 and ADMIN_USERNAME != exclude_username:
            users.append(ADMIN_USERNAME)

        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT username FROM admin_accounts WHERE admin_level >= ? ORDER BY username ASC",
                (min_level,),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            uname = row["username"]
            if uname == exclude_username or uname == ADMIN_USERNAME:
                continue
            users.append(uname)
        return users

    def _reviewer_vote_weight(self, level: int) -> int:
        # lv3 vote counts as two lv2 votes.
        return 2 if level >= 3 else 1

    def _compute_reviewer_pool_weight(self, reviewers: list[str], scope: str) -> int:
        if not reviewers:
            return 0
        if scope == "lv3":
            # All reviewers are lv3.
            return len(reviewers) * self._reviewer_vote_weight(3)

        # scope lv2plus: include both lv2/lv3 weights.
        total = self._reviewer_vote_weight(3) if ADMIN_USERNAME in reviewers else 0
        db_reviewers = [u for u in reviewers if u != ADMIN_USERNAME]
        if not db_reviewers:
            return total

        conn = get_db()
        try:
            placeholders = ",".join("?" for _ in db_reviewers)
            rows = conn.execute(
                f"SELECT username, admin_level FROM admin_accounts WHERE username IN ({placeholders})",
                tuple(db_reviewers),
            ).fetchall()
        finally:
            conn.close()
        level_map = {r["username"]: int(r["admin_level"] or 2) for r in rows}
        for uname in db_reviewers:
            total += self._reviewer_vote_weight(level_map.get(uname, 2))
        return total

    def _finalize_publish_request_if_due(self, conn: sqlite3.Connection, req: sqlite3.Row):
        if req["status"] != "pending":
            return req
        expires_at = req["expires_at"]
        if not expires_at:
            return req
        try:
            exp_ts = datetime.fromisoformat(expires_at).timestamp()
        except ValueError:
            return req
        if time.time() < exp_ts:
            return req

        agree_weight = conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
            FROM publish_request_votes
            WHERE request_id = ? AND vote = 'approve'
            """,
            (req["id"],),
        ).fetchone()[0]
        total_votes = conn.execute(
            "SELECT COUNT(*) FROM publish_request_votes WHERE request_id = ?",
            (req["id"],),
        ).fetchone()[0]

        threshold_weight = int(req["approve_threshold_weight"] or 0)
        now = now_iso()
        if total_votes == 0:
            conn.execute(
                "UPDATE publish_requests SET status = 'rejected', decided_at = ?, decided_note = ? WHERE id = ?",
                (now, "timeout: no votes", req["id"]),
            )
        elif agree_weight >= threshold_weight:
            conn.execute(
                "UPDATE publish_requests SET status = 'approved', decided_at = ?, decided_note = ? WHERE id = ?",
                (now, "timeout: approved by weighted majority", req["id"]),
            )
            conn.execute(
                "UPDATE products SET status = 'published', published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?",
                (now, now, req["product_id"]),
            )
        else:
            conn.execute(
                "UPDATE publish_requests SET status = 'rejected', decided_at = ?, decided_note = ? WHERE id = ?",
                (now, "timeout: weighted majority not reached", req["id"]),
            )

        return conn.execute("SELECT * FROM publish_requests WHERE id = ?", (req["id"],)).fetchone()

    def handle_publish_request_create(self):
        sess = self.get_session()
        if not sess:
            return self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        _, admin = sess
        requester = admin["username"]
        requester_level = max(1, min(3, int(admin.get("admin_level", 1))))

        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        product_id = body.get("product_id")
        if product_id is None:
            return self.send_json({"error": "product_id required"}, status=HTTPStatus.BAD_REQUEST)
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return self.send_json({"error": "invalid product_id"}, status=HTTPStatus.BAD_REQUEST)

        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if not row:
                return self.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)
            if row["status"] == "published":
                return self.send_json({"error": "product already published"}, status=HTTPStatus.CONFLICT)
            if not row["file_path"]:
                return self.send_json({"error": "product has no package file"}, status=HTTPStatus.BAD_REQUEST)

            # lv3 can publish directly without review.
            if requester_level >= 3:
                now = now_iso()
                conn.execute(
                    "UPDATE products SET status = 'published', published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?",
                    (now, now, product_id),
                )
                conn.commit()
                new_row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
                out = self.product_row_dict(new_row)
                out["direct_published"] = True
                return self.send_json(out)

            pending = conn.execute(
                "SELECT id FROM publish_requests WHERE product_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()
            if pending:
                return self.send_json({"error": "publish request already pending"}, status=HTTPStatus.CONFLICT)

            scope, min_level = self._publish_reviewer_scope(requester_level)
            reviewers = self._list_reviewer_usernames(min_level=min_level, exclude_username=requester)
            pool_count = len(reviewers)
            if pool_count <= 0:
                return self.send_json({"error": "no eligible reviewers found"}, status=HTTPStatus.CONFLICT)
            pool_weight = self._compute_reviewer_pool_weight(reviewers, scope)
            threshold_weight = (pool_weight // 2) + 1
            expires_at = datetime.fromtimestamp(time.time() + PUBLISH_REVIEW_TIMEOUT_MINUTES * 60, timezone.utc).isoformat()

            cur = conn.execute(
                """
                INSERT INTO publish_requests (
                    product_id, requested_by, requester_level, reviewer_scope,
                    reviewer_pool_count, reviewer_pool_weight, approve_threshold_weight, status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (product_id, requester, requester_level, scope, pool_count, pool_weight, threshold_weight, now_iso(), expires_at),
            )
            req_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        self.send_json(
            {
                "ok": True,
                "request_id": req_id,
                "product_id": product_id,
                "reviewer_scope": scope,
                "reviewer_pool_count": pool_count,
                "reviewer_pool_weight": pool_weight,
                "approve_threshold_weight": threshold_weight,
                "expires_at": expires_at,
            },
            status=HTTPStatus.CREATED,
        )

    def handle_publish_request_vote(self, path: str):
        sess = self.get_session()
        if not sess:
            return self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        _, admin = sess
        reviewer = admin["username"]
        reviewer_level = max(1, min(3, int(admin.get("admin_level", 1))))

        parts = [p for p in path.split("/") if p]
        if len(parts) != 5:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            req_id = int(parts[3])
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        vote = (body.get("vote") or "").strip().lower()
        if vote not in {"approve", "reject"}:
            return self.send_json({"error": "vote must be approve/reject"}, status=HTTPStatus.BAD_REQUEST)
        note = (body.get("note") or "").strip()[:1000]

        conn = get_db()
        try:
            begin_immediate_with_retry(conn)
            req = conn.execute("SELECT * FROM publish_requests WHERE id = ?", (req_id,)).fetchone()
            if not req:
                conn.rollback()
                return self.send_json({"error": "request not found"}, status=HTTPStatus.NOT_FOUND)
            req = self._finalize_publish_request_if_due(conn, req)
            if req["status"] != "pending":
                conn.rollback()
                return self.send_json({"error": "request already decided"}, status=HTTPStatus.CONFLICT)
            if req["requested_by"] == reviewer:
                conn.rollback()
                return self.send_json({"error": "requester cannot vote own request"}, status=HTTPStatus.FORBIDDEN)

            required_level = 2 if req["reviewer_scope"] == "lv2plus" else 3
            if reviewer_level < required_level:
                conn.rollback()
                return self.send_json({"error": f"lv{required_level} reviewer required"}, status=HTTPStatus.FORBIDDEN)

            if req["reviewer_scope"] == "lv3" and reviewer != ADMIN_USERNAME:
                acc = conn.execute("SELECT admin_level FROM admin_accounts WHERE username = ?", (reviewer,)).fetchone()
                if not acc or int(acc["admin_level"] or 1) < 3:
                    conn.rollback()
                    return self.send_json({"error": "lv3 reviewer required"}, status=HTTPStatus.FORBIDDEN)

            existed = conn.execute(
                "SELECT 1 FROM publish_request_votes WHERE request_id = ? AND reviewer_username = ? LIMIT 1",
                (req_id, reviewer),
            ).fetchone()
            if existed:
                conn.rollback()
                return self.send_json({"error": "already voted"}, status=HTTPStatus.CONFLICT)

            conn.execute(
                """
                INSERT INTO publish_request_votes (request_id, reviewer_username, reviewer_level, vote, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (req_id, reviewer, reviewer_level, vote, note, now_iso()),
            )

            agree_weight = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
                FROM publish_request_votes
                WHERE request_id = ? AND vote = 'approve'
                """,
                (req_id,),
            ).fetchone()[0]
            reject_weight = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
                FROM publish_request_votes
                WHERE request_id = ? AND vote = 'reject'
                """,
                (req_id,),
            ).fetchone()[0]
            threshold_weight = int(req["approve_threshold_weight"] or 0)
            pool_weight = int(req["reviewer_pool_weight"] or 0)
            max_possible_approve_weight = pool_weight - reject_weight

            if agree_weight >= threshold_weight:
                now = now_iso()
                conn.execute(
                    "UPDATE publish_requests SET status = 'approved', decided_at = ?, decided_note = ? WHERE id = ?",
                    (now, note, req_id),
                )
                conn.execute(
                    "UPDATE products SET status = 'published', published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?",
                    (now, now, req["product_id"]),
                )
                final_status = "approved"
            elif max_possible_approve_weight < threshold_weight:
                now = now_iso()
                conn.execute(
                    "UPDATE publish_requests SET status = 'rejected', decided_at = ?, decided_note = ? WHERE id = ?",
                    (now, note, req_id),
                )
                final_status = "rejected"
            else:
                final_status = "pending"

            conn.commit()
        finally:
            conn.close()

        self.send_json(
            {
                "ok": True,
                "status": final_status,
                "agree_weight": agree_weight,
                "reject_weight": reject_weight,
                "threshold_weight": threshold_weight,
            }
        )

    def handle_publish_requests_get(self):
        sess = self.get_session()
        if not sess:
            return self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        _, admin = sess
        me = admin["username"]
        my_level = max(1, min(3, int(admin.get("admin_level", 1))))

        conn = get_db()
        try:
            begin_immediate_with_retry(conn)
            if my_level <= 1 and not bool(admin.get("is_super")):
                rows = conn.execute(
                    """
                    SELECT r.*, p.name AS product_name, p.slug AS product_slug
                    FROM publish_requests r
                    JOIN products p ON p.id = r.product_id
                    WHERE r.requested_by = ?
                    ORDER BY r.id DESC
                    LIMIT 300
                    """,
                    (me,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT r.*, p.name AS product_name, p.slug AS product_slug
                    FROM publish_requests r
                    JOIN products p ON p.id = r.product_id
                    ORDER BY r.id DESC
                    LIMIT 300
                    """
                ).fetchall()

            items = []
            for r in rows:
                r = self._finalize_publish_request_if_due(conn, r)
                agree_weight = conn.execute(
                    """
                    SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
                    FROM publish_request_votes WHERE request_id = ? AND vote = 'approve'
                    """,
                    (r["id"],),
                ).fetchone()[0]
                reject_weight = conn.execute(
                    """
                    SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
                    FROM publish_request_votes WHERE request_id = ? AND vote = 'reject'
                    """,
                    (r["id"],),
                ).fetchone()[0]
                my_vote = conn.execute(
                    "SELECT vote FROM publish_request_votes WHERE request_id = ? AND reviewer_username = ?",
                    (r["id"], me),
                ).fetchone()
                required_level = 2 if r["reviewer_scope"] == "lv2plus" else 3
                expired = False
                if r["expires_at"]:
                    try:
                        expired = datetime.fromisoformat(r["expires_at"]).timestamp() <= time.time()
                    except ValueError:
                        expired = False
                can_vote = (
                    r["status"] == "pending"
                    and r["requested_by"] != me
                    and my_level >= required_level
                    and my_vote is None
                    and not expired
                )
                items.append(
                    {
                        "id": r["id"],
                        "product_id": r["product_id"],
                        "product_name": r["product_name"],
                        "product_slug": r["product_slug"],
                        "requested_by": r["requested_by"],
                        "requester_level": r["requester_level"],
                        "reviewer_scope": r["reviewer_scope"],
                        "reviewer_pool_count": r["reviewer_pool_count"],
                        "reviewer_pool_weight": int(r["reviewer_pool_weight"] or 0),
                        "approve_threshold_weight": int(r["approve_threshold_weight"] or 0),
                        "status": r["status"],
                        "created_at": r["created_at"],
                        "expires_at": r["expires_at"],
                        "decided_at": r["decided_at"],
                        "agree_weight": agree_weight,
                        "reject_weight": reject_weight,
                        "my_vote": my_vote["vote"] if my_vote else None,
                        "expired": expired,
                        "can_vote": can_vote,
                    }
                )
            conn.commit()
        finally:
            conn.close()

        self.send_json({"items": items})

    def _review_delete_request(self, path: str, decision: str):
        sess = self.get_session()
        if not sess:
            return self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        _, admin = sess
        reviewer = admin["username"]

        parts = [p for p in path.split("/") if p]
        if len(parts) != 5:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            req_id = int(parts[3])
            body = self.read_json_body() if self.headers.get("Content-Length") else {}
        except Exception:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        note = (body.get("note") or "").strip()[:1000]

        conn = get_db()
        try:
            begin_immediate_with_retry(conn)
            req = conn.execute("SELECT * FROM product_delete_requests WHERE id = ?", (req_id,)).fetchone()
            if not req:
                conn.rollback()
                return self.send_json({"error": "request not found"}, status=HTTPStatus.NOT_FOUND)
            if req["status"] != "pending":
                conn.rollback()
                return self.send_json({"error": "request already reviewed"}, status=HTTPStatus.CONFLICT)
            if req["owner_username"] != reviewer:
                conn.rollback()
                return self.send_json({"error": "only owner can review"}, status=HTTPStatus.FORBIDDEN)

            now = now_iso()
            if decision == "approve":
                row = conn.execute("SELECT * FROM products WHERE id = ?", (req["product_id"],)).fetchone()
                if row:
                    conn.execute("DELETE FROM downloads WHERE product_id = ?", (req["product_id"],))
                    conn.execute("DELETE FROM products WHERE id = ?", (req["product_id"],))
                conn.execute(
                    """
                    UPDATE product_delete_requests
                    SET status = 'approved', decided_at = ?, decided_by = ?, decision_note = ?
                    WHERE id = ?
                    """,
                    (now, reviewer, note, req_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE product_delete_requests
                    SET status = 'rejected', decided_at = ?, decided_by = ?, decision_note = ?
                    WHERE id = ?
                    """,
                    (now, reviewer, note, req_id),
                )
            conn.commit()
        finally:
            conn.close()

        return self.send_json({"ok": True, "status": "approved" if decision == "approve" else "rejected"})

    def handle_delete_request_approve(self, path: str):
        return self._review_delete_request(path, "approve")

    def handle_delete_request_reject(self, path: str):
        return self._review_delete_request(path, "reject")

    def handle_admin_inbox_get(self):
        sess = self.get_session()
        if not sess:
            return self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        _, admin = sess
        me = admin["username"]
        my_level = max(1, min(3, int(admin.get("admin_level", 1))))

        conn = get_db()
        try:
            # Download request approval inbox (lv2+)
            download_items = []
            video_request_items = []
            if my_level >= 2:
                drows = conn.execute(
                    """
                    SELECT r.*, u.username, p.name as product_name, p.slug as product_slug
                    FROM download_requests r
                    JOIN users u ON u.id = r.user_id
                    JOIN products p ON p.id = r.product_id
                    WHERE r.status = 'pending'
                    ORDER BY r.id DESC
                    LIMIT 200
                    """
                ).fetchall()
                for r in drows:
                    download_items.append(
                        {
                            "type": "download_request",
                            "id": r["id"],
                            "username": r["username"],
                            "product_name": r["product_name"],
                            "product_slug": r["product_slug"],
                            "reason": r["reason"],
                            "created_at": r["created_at"],
                        }
                    )
                vrows = conn.execute(
                    """
                    SELECT r.*, u.username
                    FROM agnes_video_requests r
                    JOIN users u ON u.id = r.user_id
                    WHERE r.status = 'pending'
                    ORDER BY r.id DESC
                    LIMIT 200
                    """
                ).fetchall()
                for r in vrows:
                    video_request_items.append(
                        {
                            "type": "agnes_video_request",
                            "id": int(r["id"]),
                            "username": r["username"] or "",
                            "reason": r["reason"] or "",
                            "created_at": r["created_at"] or None,
                        }
                    )

            # Publish approvals requiring my vote
            publish_items = []
            prows = conn.execute(
                """
                SELECT r.*, p.name AS product_name, p.slug AS product_slug
                FROM publish_requests r
                JOIN products p ON p.id = r.product_id
                WHERE r.status = 'pending'
                ORDER BY r.id DESC
                LIMIT 300
                """
            ).fetchall()
            for r in prows:
                r = self._finalize_publish_request_if_due(conn, r)
                if r["status"] != "pending":
                    continue
                my_vote = conn.execute(
                    "SELECT vote FROM publish_request_votes WHERE request_id = ? AND reviewer_username = ?",
                    (r["id"], me),
                ).fetchone()
                required_level = 2 if r["reviewer_scope"] == "lv2plus" else 3
                can_vote = (
                    r["requested_by"] != me
                    and my_level >= required_level
                    and my_vote is None
                )
                if can_vote:
                    agree_weight = conn.execute(
                        """
                        SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
                        FROM publish_request_votes WHERE request_id = ? AND vote = 'approve'
                        """,
                        (r["id"],),
                    ).fetchone()[0]
                    publish_items.append(
                        {
                            "type": "publish_request",
                            "id": r["id"],
                            "product_name": r["product_name"],
                            "product_slug": r["product_slug"],
                            "requested_by": r["requested_by"],
                            "reviewer_scope": r["reviewer_scope"],
                            "agree_weight": agree_weight,
                            "approve_threshold_weight": int(r["approve_threshold_weight"] or 0),
                            "expires_at": r["expires_at"],
                            "created_at": r["created_at"],
                        }
                    )

            # Delete requests inbox for owner
            delete_items = []
            del_rows = conn.execute(
                """
                SELECT * FROM product_delete_requests
                WHERE status = 'pending' AND owner_username = ?
                ORDER BY id DESC
                LIMIT 200
                """,
                (me,),
            ).fetchall()
            for r in del_rows:
                delete_items.append(
                    {
                        "type": "delete_request",
                        "id": r["id"],
                        "product_id": r["product_id"],
                        "product_name": r["product_name"],
                        "product_slug": r["product_slug"],
                        "requested_by": r["requested_by"],
                        "requester_level": r["requester_level"],
                        "reason": r["reason"],
                        "created_at": r["created_at"],
                    }
                )
        finally:
            conn.close()

        self.send_json(
            {
                "download_requests": download_items,
                "agnes_video_requests": video_request_items,
                "publish_requests": publish_items,
                "delete_requests": delete_items,
                "unread_count": len(download_items) + len(video_request_items) + len(publish_items) + len(delete_items),
            }
        )

    def handle_user_me(self):
        sess = self.get_user_session()
        if not sess:
            return self.send_json({"loggedIn": False})
        _, data = sess
        self.send_json({"loggedIn": True, "username": data["username"], "user_id": data["user_id"]})

    def handle_user_history(self):
        sess = self.require_user_auth()
        if not sess:
            return
        _, user = sess
        user_id = user["user_id"]

        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT d.*, p.name AS product_name, p.slug AS product_slug, p.version AS product_version, p.file_name AS product_file
                FROM downloads d
                LEFT JOIN products p ON p.id = d.product_id
                WHERE d.user_id = ?
                ORDER BY d.downloaded_at DESC
                LIMIT 200
                """,
                (user_id,),
            ).fetchall()
        finally:
            conn.close()

        items = [
            {
                "id": r["id"],
                "product_id": r["product_id"],
                "product_name": r["product_name"] or "",
                "product_slug": r["product_slug"] or "",
                "product_version": r["product_version"] or "",
                "product_file": r["product_file"] or "",
                "downloaded_at": r["downloaded_at"],
            }
            for r in rows
        ]
        self.send_json({"items": items})

    def handle_user_download_quota(self):
        sess = self.require_user_auth()
        if not sess:
            return
        _, user = sess
        user_id = user["user_id"]

        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT p.id AS product_id, p.name AS product_name, p.slug AS product_slug, p.version AS product_version,
                       CASE WHEN d0.id IS NULL THEN 0 ELSE 1 END AS used_first_download,
                       CASE WHEN ra.id IS NULL THEN 0 ELSE 1 END AS has_unused_approved_request,
                       CASE WHEN rp.id IS NULL THEN 0 ELSE 1 END AS has_pending_request
                FROM products p
                LEFT JOIN downloads d0
                  ON d0.id = (
                    SELECT dsub.id
                    FROM downloads dsub
                    WHERE dsub.product_id = p.id AND dsub.user_id = ?
                    ORDER BY dsub.id ASC
                    LIMIT 1
                  )
                LEFT JOIN download_requests ra
                  ON ra.id = (
                    SELECT rsub.id
                    FROM download_requests rsub
                    WHERE rsub.product_id = p.id
                      AND rsub.user_id = ?
                      AND rsub.status = 'approved'
                      AND rsub.consumed_at IS NULL
                    ORDER BY rsub.id DESC
                    LIMIT 1
                  )
                LEFT JOIN download_requests rp
                  ON rp.id = (
                    SELECT rsub.id
                    FROM download_requests rsub
                    WHERE rsub.product_id = p.id
                      AND rsub.user_id = ?
                      AND rsub.status = 'pending'
                    ORDER BY rsub.id DESC
                    LIMIT 1
                  )
                WHERE p.status = 'published'
                ORDER BY p.name ASC
                """,
                (user_id, user_id, user_id),
            ).fetchall()
        finally:
            conn.close()

        items = []
        for r in rows:
            used_first = bool(r["used_first_download"])
            has_unused_approved = bool(r["has_unused_approved_request"])
            remaining_downloads = 1 if (not used_first or has_unused_approved) else 0
            items.append(
                {
                    "product_id": r["product_id"],
                    "product_name": r["product_name"] or "",
                    "product_slug": r["product_slug"] or "",
                    "product_version": r["product_version"] or "",
                    "used_first_download": used_first,
                    "has_unused_approved_request": has_unused_approved,
                    "has_pending_request": bool(r["has_pending_request"]),
                    "remaining_downloads": remaining_downloads,
                }
            )
        self.send_json({"items": items})

    def handle_user_requests(self):
        sess = self.require_user_auth()
        if not sess:
            return
        _, user = sess
        user_id = user["user_id"]

        conn = get_db()
        try:
            download_rows = conn.execute(
                """
                SELECT r.*, p.name AS product_name, p.slug AS product_slug
                FROM download_requests r
                LEFT JOIN products p ON p.id = r.product_id
                WHERE r.user_id = ?
                ORDER BY r.id DESC
                LIMIT 200
                """,
                (user_id,),
            ).fetchall()
            video_rows = conn.execute(
                """
                SELECT id, reason, status, created_at, reviewed_at, review_note, consumed_at, consumed_task_id
                FROM agnes_video_requests
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 200
                """,
                (user_id,),
            ).fetchall()
        finally:
            conn.close()

        items = [
            {
                "id": r["id"],
                "product_id": r["product_id"],
                "product_name": r["product_name"] or "",
                "product_slug": r["product_slug"] or "",
                "reason": r["reason"] or "",
                "status": r["status"],
                "created_at": r["created_at"],
                "reviewed_at": r["reviewed_at"],
                "review_note": r["review_note"],
                "consumed_at": r["consumed_at"],
            }
            for r in download_rows
        ]
        video_items = [
            {
                "id": int(r["id"]),
                "reason": r["reason"] or "",
                "status": r["status"] or "",
                "created_at": r["created_at"] or None,
                "reviewed_at": r["reviewed_at"] or None,
                "review_note": r["review_note"] or "",
                "consumed_at": r["consumed_at"] or None,
                "consumed_task_id": r["consumed_task_id"] or "",
            }
            for r in video_rows
        ]
        self.send_json({"items": items, "agnes_video_items": video_items})

    def handle_user_notifications(self):
        sess = self.require_user_auth()
        if not sess:
            return
        _, user = sess
        user_id = user["user_id"]

        conn = get_db()
        try:
            subscribed = conn.execute(
                "SELECT 1 FROM user_subscriptions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not subscribed:
                return self.send_json({"subscribed": False, "items": []})

            rows = conn.execute(
                """
                SELECT id, name, slug, version, announcement, published_at, updated_at
                FROM products
                WHERE status = 'published' AND TRIM(COALESCE(announcement, '')) != ''
                ORDER BY COALESCE(published_at, updated_at) DESC
                LIMIT 20
                """,
            ).fetchall()
        finally:
            conn.close()

        items = [
            {
                "product_id": r["id"],
                "product_name": r["name"],
                "product_slug": r["slug"],
                "version": r["version"],
                "announcement": r["announcement"],
                "published_at": r["published_at"] or r["updated_at"],
            }
            for r in rows
        ]
        self.send_json({"subscribed": True, "items": items})

    def handle_account_me(self):
        # Admin checked FIRST to avoid being masked by stale user cookie
        admin_sess = self.get_session()
        if admin_sess:
            _, admin = admin_sess
            return self.send_json(
                {
                    "loggedIn": True,
                    "role": "admin",
                    "username": admin.get("username", ""),
                    "adminLevel": int(admin.get("admin_level", 1)),
                    "isSuper": bool(admin.get("is_super")),
                }
            )
        user_sess = self.get_user_session()
        if user_sess:
            _, user = user_sess
            return self.send_json(
                {
                    "loggedIn": True,
                    "role": "user",
                    "username": user.get("username", ""),
                    "user_id": user.get("user_id"),
                }
            )
        return self.send_json({"loggedIn": False, "role": "guest"})

    def handle_subscribe(self):
        user_sess = self.get_user_session()
        if not user_sess:
            admin_sess = self.get_session()
            if admin_sess:
                return self.send_json({"ok": True, "message": "admin session, no subscribe needed"})
            self.send_json({"error": "user login required"}, status=HTTPStatus.UNAUTHORIZED)
            return
        _, user = user_sess
        user_id = user["user_id"]
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO user_subscriptions (user_id, created_at) VALUES (?, ?)",
                (user_id, now_iso()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return self.send_json({"ok": True, "message": "already subscribed"})
        finally:
            conn.close()

        self.send_json({"ok": True})

    def handle_public_products(self):
        parsed = urlparse(self.path)
        query = parsed.query or ""
        params = {}
        if query:
            for pair in query.split("&"):
                if not pair:
                    continue
                if "=" not in pair:
                    continue
                key, val = pair.split("=", 1)
                params[key] = unquote(val)

        search = (params.get("q") or "").strip()
        category = (params.get("category") or "").strip()
        version = (params.get("version") or "").strip()
        tags_raw = (params.get("tags") or "").strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        sort = (params.get("sort") or "latest").strip()
        order_sql = "ORDER BY COALESCE(p.published_at, p.updated_at) DESC"
        if sort == "downloads":
            order_sql = "ORDER BY download_count DESC"
        elif sort == "name":
            order_sql = "ORDER BY p.name ASC"
        elif sort == "version":
            order_sql = "ORDER BY p.version DESC"

        clauses = ["p.status = 'published'"]
        values = []
        if search:
            like = f"%{search}%"
            clauses.append("(p.name LIKE ? OR p.summary LIKE ? OR p.description LIKE ? OR p.category LIKE ? OR p.tags LIKE ?)")
            values.extend([like, like, like, like, like])
        if category:
            clauses.append("p.category = ?")
            values.append(category)
        if version:
            clauses.append("p.version = ?")
            values.append(version)
        for tag in tags:
            clauses.append("p.tags LIKE ?")
            values.append(f"%{tag}%")

        where_sql = " AND ".join(clauses)
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT p.*, COUNT(d.id) as download_count
                FROM products p
                LEFT JOIN downloads d ON d.product_id = p.id
                WHERE {where_sql}
                GROUP BY p.id
                {order_sql}
                """
                .format(where_sql=where_sql, order_sql=order_sql),
                values,
            ).fetchall()
        finally:
            conn.close()

        self.send_json({"items": [self.product_row_dict(r) for r in rows]})

    def handle_public_products_meta(self):
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT category, tags FROM products WHERE status = 'published'"
            ).fetchall()
        finally:
            conn.close()

        categories = set()
        tags = set()
        for r in rows:
            category = (r["category"] or "").strip()
            if category:
                categories.add(category)
            raw_tags = (r["tags"] or "").split(",")
            for tag in raw_tags:
                tag = tag.strip()
                if tag:
                    tags.add(tag)
        self.send_json({"categories": sorted(categories), "tags": sorted(tags)})

    def handle_public_product_detail(self, path: str):
        key = path.split("/api/products/", 1)[1].strip()
        if not key:
            return self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        admin_ctx = self.get_session()
        admin_data = admin_ctx[1] if admin_ctx else None
        user_ctx = self.get_user_session()
        user_id = user_ctx[1]["user_id"] if user_ctx else None

        conn = get_db()
        try:
            if key.isdigit():
                row = conn.execute(
                    "SELECT * FROM products WHERE id = ? AND status = 'published'", (int(key),)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM products WHERE slug = ? AND status = 'published'", (key,)
                ).fetchone()
            if not row:
                return self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            count = conn.execute("SELECT COUNT(*) FROM downloads WHERE product_id = ?", (row["id"],)).fetchone()[0]
            out = self.product_row_dict(row)
            out["download_count"] = count
            out["requires_login"] = True
            out["can_download_now"] = False
            out["download_rule"] = "one-time-per-user"
            out["user_download_state"] = {
                "loggedIn": user_id is not None,
                "is_admin": False,
                "has_downloaded": False,
                "has_approved_request": False,
                "pending_request": False,
            }

            if admin_data:
                out["requires_login"] = False
                out["can_download_now"] = bool(row["file_path"])
                out["download_rule"] = "admin-unlimited"
                out["user_download_state"] = {
                    "loggedIn": True,
                    "is_admin": True,
                    "username": admin_data.get("username", ""),
                    "admin_level": int(admin_data.get("admin_level", 1)),
                    "has_downloaded": False,
                    "has_approved_request": False,
                    "pending_request": False,
                }
            elif user_id is not None:
                done = conn.execute(
                    "SELECT 1 FROM downloads WHERE product_id = ? AND user_id = ? LIMIT 1",
                    (row["id"], user_id),
                ).fetchone()
                approved = conn.execute(
                    """
                    SELECT id FROM download_requests
                    WHERE product_id = ? AND user_id = ? AND status = 'approved' AND consumed_at IS NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    (row["id"], user_id),
                ).fetchone()
                pending = conn.execute(
                    """
                    SELECT 1 FROM download_requests
                    WHERE product_id = ? AND user_id = ? AND status = 'pending'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (row["id"], user_id),
                ).fetchone()
                has_downloaded = done is not None
                has_approved = approved is not None
                out["can_download_now"] = (not has_downloaded) or has_approved
                out["user_download_state"] = {
                    "loggedIn": True,
                    "is_admin": False,
                    "has_downloaded": has_downloaded,
                    "has_approved_request": has_approved,
                    "pending_request": pending is not None,
                }
        finally:
            conn.close()

        self.send_json(out)

    def handle_user_download_request(self, path: str):
        sess = self.require_user_auth()
        if not sess:
            return
        _, user = sess
        user_id = user["user_id"]

        key = path.split("/api/products/", 1)[1].rsplit("/request-download", 1)[0].strip()
        if not key:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        try:
            body = self.read_json_body()
        except Exception:
            body = {}
        reason = (body.get("reason") or "").strip()

        conn = get_db()
        try:
            if key.isdigit():
                row = conn.execute(
                    "SELECT * FROM products WHERE id = ? AND status = 'published'", (int(key),)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM products WHERE slug = ? AND status = 'published'", (key,)
                ).fetchone()
            if not row:
                return self.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)

            product_id = row["id"]
            done = conn.execute(
                "SELECT 1 FROM downloads WHERE product_id = ? AND user_id = ? LIMIT 1",
                (product_id, user_id),
            ).fetchone()
            if not done:
                return self.send_json({"error": "user has not consumed first download yet"}, status=HTTPStatus.BAD_REQUEST)

            pending = conn.execute(
                """
                SELECT id FROM download_requests
                WHERE user_id = ? AND product_id = ? AND status = 'pending'
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, product_id),
            ).fetchone()
            if pending:
                return self.send_json({"error": "request already pending"}, status=HTTPStatus.CONFLICT)

            conn.execute(
                """
                INSERT INTO download_requests (user_id, product_id, reason, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (user_id, product_id, reason[:1000], now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

        self.send_json({"ok": True, "message": "request submitted"})

    def handle_admin_download_requests_get(self, path: str):
        if not self.require_auth():
            return

        parsed = urlparse(path)
        view = "pending"
        if "?" in path:
            query = parsed.query
            for pair in query.split("&"):
                if pair.startswith("status="):
                    view = pair.split("=", 1)[1] or "pending"
        if view not in {"pending", "approved", "rejected", "all"}:
            view = "pending"

        conn = get_db()
        try:
            sql = """
                SELECT r.*, u.username, p.name as product_name, p.slug as product_slug
                FROM download_requests r
                JOIN users u ON u.id = r.user_id
                JOIN products p ON p.id = r.product_id
            """
            params = ()
            if view != "all":
                sql += " WHERE r.status = ? "
                params = (view,)
            sql += " ORDER BY r.id DESC LIMIT 300"
            rows = conn.execute(sql, params).fetchall()
            items = []
            for r in rows:
                items.append(
                    {
                        "id": r["id"],
                        "user_id": r["user_id"],
                        "username": r["username"],
                        "product_id": r["product_id"],
                        "product_name": r["product_name"],
                        "product_slug": r["product_slug"],
                        "reason": r["reason"],
                        "status": r["status"],
                        "review_note": r["review_note"],
                        "created_at": r["created_at"],
                        "reviewed_at": r["reviewed_at"],
                        "reviewed_by": r["reviewed_by"],
                        "consumed_at": r["consumed_at"],
                    }
                )
        finally:
            conn.close()

        self.send_json({"items": items})

    def _admin_review_request(self, path: str, new_status: str):
        if not self.require_level2_auth():
            return
        parts = [p for p in path.split("/") if p]
        if len(parts) != 5:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            req_id = int(parts[3])
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        note = (body.get("note") or "").strip()[:1000]
        admin = self.get_session()[1]["username"]

        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM download_requests WHERE id = ?", (req_id,)).fetchone()
            if not row:
                return self.send_json({"error": "request not found"}, status=HTTPStatus.NOT_FOUND)
            if row["status"] != "pending":
                return self.send_json({"error": "request already reviewed"}, status=HTTPStatus.CONFLICT)
            conn.execute(
                """
                UPDATE download_requests
                SET status = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
                """,
                (new_status, note, now_iso(), admin, req_id),
            )
            conn.commit()
        finally:
            conn.close()

        self.send_json({"ok": True, "status": new_status})

    def handle_admin_download_request_approve(self, path: str):
        return self._admin_review_request(path, "approved")

    def handle_admin_download_request_reject(self, path: str):
        return self._admin_review_request(path, "rejected")

    def handle_admin_agnes_video_requests_get(self, path: str):
        if not self.require_level2_auth():
            return
        parsed = urlparse(path)
        view = "pending"
        query = parsed.query or ""
        for pair in query.split("&"):
            if pair.startswith("status="):
                view = pair.split("=", 1)[1] or "pending"
        if view not in {"pending", "approved", "rejected", "all"}:
            view = "pending"

        conn = get_db()
        try:
            sql = """
                SELECT r.*, u.username
                FROM agnes_video_requests r
                JOIN users u ON u.id = r.user_id
            """
            params = ()
            if view != "all":
                sql += " WHERE r.status = ? "
                params = (view,)
            sql += " ORDER BY r.id DESC LIMIT 300"
            rows = conn.execute(sql, params).fetchall()
            items = []
            for r in rows:
                items.append(
                    {
                        "id": int(r["id"]),
                        "user_id": int(r["user_id"]),
                        "username": r["username"] or "",
                        "reason": r["reason"] or "",
                        "status": r["status"] or "",
                        "review_note": r["review_note"] or "",
                        "created_at": r["created_at"] or None,
                        "reviewed_at": r["reviewed_at"] or None,
                        "reviewed_by": r["reviewed_by"] or "",
                        "consumed_at": r["consumed_at"] or None,
                        "consumed_task_id": r["consumed_task_id"] or "",
                    }
                )
        finally:
            conn.close()
        self.send_json({"items": items})

    def _admin_review_agnes_video_request(self, path: str, new_status: str):
        if not self.require_level2_auth():
            return
        parts = [p for p in path.split("/") if p]
        if len(parts) != 5:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            req_id = int(parts[3])
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        note = str(body.get("note") or "").strip()[:1000]
        admin = self.get_session()[1]["username"]
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM agnes_video_requests WHERE id = ?", (req_id,)).fetchone()
            if not row:
                return self.send_json({"error": "request not found"}, status=HTTPStatus.NOT_FOUND)
            if row["status"] != "pending":
                return self.send_json({"error": "request already reviewed"}, status=HTTPStatus.CONFLICT)
            conn.execute(
                """
                UPDATE agnes_video_requests
                SET status = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
                """,
                (new_status, note, now_iso(), admin, req_id),
            )
            conn.commit()
        finally:
            conn.close()
        self.send_json({"ok": True, "status": new_status})

    def handle_admin_agnes_video_request_approve(self, path: str):
        return self._admin_review_agnes_video_request(path, "approved")

    def handle_admin_agnes_video_request_reject(self, path: str):
        return self._admin_review_agnes_video_request(path, "rejected")

    def handle_admin_products_get(self, path: str):
        if not self.require_auth():
            return

        parts = [p for p in path.split("/") if p]
        conn = get_db()
        try:
            if len(parts) == 3:
                rows = conn.execute(
                    """
                    SELECT p.*, COUNT(d.id) as download_count
                    FROM products p
                    LEFT JOIN downloads d ON d.product_id = p.id
                    GROUP BY p.id
                    ORDER BY p.updated_at DESC
                    """
                ).fetchall()
                return self.send_json({"items": [self.product_row_dict(r) for r in rows]})

            pid = int(parts[3])
            row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            if not row:
                return self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            count = conn.execute("SELECT COUNT(*) FROM downloads WHERE product_id = ?", (pid,)).fetchone()[0]
            out = self.product_row_dict(row)
            out["download_count"] = count
            self.send_json(out)
        except (ValueError, IndexError):
            self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        finally:
            conn.close()

    def handle_admin_versions_get(self, path: str):
        if not self.require_auth():
            return
        parts = [p for p in path.split("/") if p]
        if len(parts) < 4:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            product_id = int(parts[3])
        except ValueError:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT * FROM product_versions
                WHERE product_id = ?
                ORDER BY id DESC
                LIMIT 300
                """,
                (product_id,),
            ).fetchall()
            items = []
            for row in rows:
                items.append(
                    {
                        "id": row["id"],
                        "product_id": row["product_id"],
                        "name": row["name"],
                        "slug": row["slug"],
                        "version": row["version"],
                        "summary": row["summary"],
                        "description": row["description"],
                        "changelog": row["changelog"],
                        "status": row["status"],
                        "file_name": row["file_name"],
                        "file_path": row["file_path"],
                        "file_size": row["file_size"],
                        "file_sha256": row["file_sha256"],
                        "published_at": row["published_at"],
                        "created_at": row["created_at"],
                        "created_by": row["created_by"],
                        "source": row["source"],
                    }
                )
        finally:
            conn.close()

        self.send_json({"items": items})

    def handle_admin_products_create(self):
        sess = self.get_session()
        if not sess:
            self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return
        _, admin = sess
        admin_level = max(1, min(3, int(admin.get("admin_level", 1))))
        try:
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

        name = (body.get("name") or "").strip()
        if not name:
            return self.send_json({"error": "name required"}, status=HTTPStatus.BAD_REQUEST)

        slug = slugify(body.get("slug") or name)
        summary = (body.get("summary") or "").strip()
        description = (body.get("description") or "").strip()
        category = (body.get("category") or "").strip()
        tags = (body.get("tags") or "").strip()
        announcement = (body.get("announcement") or "").strip()
        version = (body.get("version") or "0.1.0").strip()
        changelog = (body.get("changelog") or "").strip()
        status = (body.get("status") or "draft").strip()
        if status not in {"draft", "published"}:
            status = "draft"
        publish_requires_review = False
        if status == "published" and admin_level < 3:
            status = "draft"
            publish_requires_review = True

        now = now_iso()
        published_at = now if status == "published" else None

        conn = get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO products (slug, name, summary, description, category, tags, announcement, version, changelog, status, created_by, created_at, updated_at, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (slug, name, summary, description, category, tags, announcement, version, changelog, status, admin["username"], now, now, published_at),
            )
            conn.commit()
            pid = cur.lastrowid
            row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        except sqlite3.IntegrityError:
            return self.send_json({"error": "slug already exists"}, status=HTTPStatus.CONFLICT)
        finally:
            conn.close()

        self.create_product_version_snapshot(pid, admin["username"], "create")
        out = self.product_row_dict(row)
        out["publish_requires_review"] = publish_requires_review
        self.send_json(out, status=HTTPStatus.CREATED)

    def handle_admin_products_update(self, path: str):
        sess = self.get_session()
        if not sess:
            self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return
        _, admin = sess

        parts = [p for p in path.split("/") if p]
        if len(parts) < 4:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            pid = int(parts[3])
            body = self.read_json_body()
        except Exception:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            if not row:
                return self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            admin_level = max(1, min(3, int(admin.get("admin_level", 1))))
            if admin_level == 1 and row["created_by"] != admin["username"]:
                return self.send_json({"error": "lv1 can only edit own products"}, status=HTTPStatus.FORBIDDEN)
            conn.execute(
                """
                INSERT INTO product_versions (
                    product_id, name, slug, category, tags, announcement, version, summary, description, changelog, status,
                    file_name, file_path, file_size, file_sha256, published_at, created_at, created_by, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["name"],
                    row["slug"],
                    row["category"],
                    row["tags"],
                    row["announcement"],
                    row["version"],
                    row["summary"],
                    row["description"],
                    row["changelog"],
                    row["status"],
                    row["file_name"],
                    row["file_path"],
                    row["file_size"],
                    row["file_sha256"],
                    row["published_at"],
                    now_iso(),
                    admin["username"],
                    "before_update",
                ),
            )

            name = (body.get("name") if body.get("name") is not None else row["name"]).strip()
            if not name:
                return self.send_json({"error": "name required"}, status=HTTPStatus.BAD_REQUEST)
            slug = slugify(body.get("slug") if body.get("slug") is not None else row["slug"])
            summary = (body.get("summary") if body.get("summary") is not None else row["summary"]).strip()
            description = (body.get("description") if body.get("description") is not None else row["description"]).strip()
            category = (body.get("category") if body.get("category") is not None else row["category"]).strip()
            tags = (body.get("tags") if body.get("tags") is not None else row["tags"]).strip()
            announcement = (body.get("announcement") if body.get("announcement") is not None else row["announcement"]).strip()
            version = (body.get("version") if body.get("version") is not None else row["version"]).strip()
            changelog = (body.get("changelog") if body.get("changelog") is not None else row["changelog"]).strip()
            status = (body.get("status") if body.get("status") is not None else row["status"]).strip()
            if status not in {"draft", "published"}:
                status = row["status"]
            publish_requires_review = False
            if status == "published" and int(admin.get("admin_level", 1)) < 3:
                status = row["status"] if row["status"] == "published" else "draft"
                publish_requires_review = True

            published_at = row["published_at"]
            if status == "published" and not published_at:
                published_at = now_iso()
            if status == "draft":
                published_at = None

            conn.execute(
                """
                UPDATE products
                SET slug = ?, name = ?, summary = ?, description = ?, category = ?, tags = ?, announcement = ?, version = ?, changelog = ?, status = ?, updated_at = ?, published_at = ?
                WHERE id = ?
                """,
                (
                    slug,
                    name,
                    summary,
                    description,
                    category,
                    tags,
                    announcement,
                    version,
                    changelog,
                    status,
                    now_iso(),
                    published_at,
                    pid,
                ),
            )
            conn.commit()
            new_row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        except sqlite3.IntegrityError:
            return self.send_json({"error": "slug already exists"}, status=HTTPStatus.CONFLICT)
        finally:
            conn.close()

        out = self.product_row_dict(new_row)
        out["publish_requires_review"] = publish_requires_review
        self.send_json(out)

    def handle_admin_products_delete(self, path: str):
        sess = self.get_session()
        if not sess:
            self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return
        _, admin = sess

        parts = [p for p in path.split("/") if p]
        if len(parts) != 4:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        try:
            pid = int(parts[3])
        except ValueError:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        admin_level = max(1, min(3, int(admin.get("admin_level", 1))))
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            if not row:
                return self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

            owner = row["created_by"] or ""
            owner_level = 1
            if owner == ADMIN_USERNAME:
                owner_level = 3
            elif owner:
                ow = conn.execute("SELECT admin_level FROM admin_accounts WHERE username = ?", (owner,)).fetchone()
                owner_level = max(1, min(3, int(ow["admin_level"] or 1))) if ow else 1

            # Low-level admin deleting lv3-owned product requires owner's explicit approval.
            if admin_level < 3 and owner_level >= 3 and owner and owner != admin["username"]:
                pending = conn.execute(
                    """
                    SELECT id FROM product_delete_requests
                    WHERE product_id = ? AND status = 'pending'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                if pending:
                    return self.send_json(
                        {"error": "delete request already pending", "request_id": pending["id"]},
                        status=HTTPStatus.CONFLICT,
                    )

                cur = conn.execute(
                    """
                    INSERT INTO product_delete_requests (
                        product_id, product_name, product_slug, requested_by, requester_level,
                        owner_username, reason, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        row["id"],
                        row["name"] or "",
                        row["slug"] or "",
                        admin["username"],
                        admin_level,
                        owner,
                        "",
                        now_iso(),
                    ),
                )
                conn.commit()
                return self.send_json(
                    {"ok": True, "requires_owner_approval": True, "request_id": cur.lastrowid},
                    status=HTTPStatus.ACCEPTED,
                )

            file_path = row["file_path"]
            conn.execute("DELETE FROM downloads WHERE product_id = ?", (pid,))
            conn.execute("DELETE FROM product_delete_requests WHERE product_id = ?", (pid,))
            conn.execute("DELETE FROM products WHERE id = ?", (pid,))
            conn.commit()
        finally:
            conn.close()

        if file_path:
            target = (BASE_DIR / file_path).resolve()
            if target.exists() and target.is_file():
                try:
                    target.unlink()
                except OSError:
                    pass

        self.send_json({"ok": True})

    def handle_admin_upload(self, path: str):
        sess = self.get_session()
        if not sess:
            self.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return
        sess_token, admin_data = sess
        admin_level = max(1, min(3, int(admin_data.get("admin_level", 1))))
        if admin_level >= 2:
            upload_limit = LV3_UPLOAD_SIZE_LIMIT if admin_level >= 3 else LV2_UPLOAD_SIZE_LIMIT
        else:
            upload_limit = LV1_UPLOAD_SIZE_LIMIT

        parts = [p for p in path.split("/") if p]
        if len(parts) != 5 or parts[4] != "upload":
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        try:
            pid = int(parts[3])
        except ValueError:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return self.send_json({"error": "empty body"}, status=HTTPStatus.BAD_REQUEST)
        if content_length > upload_limit:
            return self.send_json(
                {"error": f"file too large for lv{admin_level}, max {upload_limit // (1024 * 1024)}MB"},
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )

        original_header = self.headers.get("X-Filename", "").strip()
        original = safe_filename(unquote(original_header))
        if not original_header:
            return self.send_json({"error": "X-Filename header required"}, status=HTTPStatus.BAD_REQUEST)
        ext = Path(original).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return self.send_json({"error": f"unsupported extension: {ext}"}, status=HTTPStatus.BAD_REQUEST)

        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        stored_name = f"p{pid}-{stamp}-{secrets.token_hex(4)}{ext}"
        target = UPLOAD_DIR / stored_name

        sha = hashlib.sha256()
        size = 0
        with target.open("wb") as out:
            remaining = content_length
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                size += len(chunk)
                if size > upload_limit:
                    out.close()
                    target.unlink(missing_ok=True)
                    return self.send_json(
                        {"error": f"file too large for lv{admin_level}, max {upload_limit // (1024 * 1024)}MB"},
                        status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    )
                sha.update(chunk)
                out.write(chunk)

        rel = str(target.relative_to(BASE_DIR)).replace("\\", "/")

        conn = get_db()
        upload_project_count = 0
        auto_promoted = False
        old_file = None
        try:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            if not row:
                target.unlink(missing_ok=True)
                return self.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)
            if admin_level == 1 and row["created_by"] != admin_data["username"]:
                target.unlink(missing_ok=True)
                return self.send_json({"error": "lv1 can only upload to own products"}, status=HTTPStatus.FORBIDDEN)

            old_file = row["file_path"]
            conn.execute(
                """
                INSERT INTO product_versions (
                    product_id, name, slug, category, tags, announcement, version, summary, description, changelog, status,
                    file_name, file_path, file_size, file_sha256, published_at, created_at, created_by, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["name"],
                    row["slug"],
                    row["category"],
                    row["tags"],
                    row["announcement"],
                    row["version"],
                    row["summary"],
                    row["description"],
                    row["changelog"],
                    row["status"],
                    row["file_name"],
                    row["file_path"],
                    row["file_size"],
                    row["file_sha256"],
                    row["published_at"],
                    now_iso(),
                    admin_data["username"],
                    "before_upload",
                ),
            )
            conn.execute(
                """
                UPDATE products
                SET file_name = ?, file_path = ?, file_size = ?, file_sha256 = ?, updated_at = ?
                WHERE id = ?
                """,
                (original, rel, size, sha.hexdigest(), now_iso(), pid),
            )

            # Track delivered project count by unique (admin, product).
            conn.execute(
                """
                INSERT INTO admin_upload_events (admin_username, product_id, uploaded_at, file_size)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(admin_username, product_id)
                DO UPDATE SET uploaded_at = excluded.uploaded_at, file_size = excluded.file_size
                """,
                (admin_data["username"], pid, now_iso(), size),
            )
            upload_project_count = conn.execute(
                "SELECT COUNT(*) FROM admin_upload_events WHERE admin_username = ?",
                (admin_data["username"],),
            ).fetchone()[0]

            if (
                not bool(admin_data.get("is_super"))
                and admin_level == 1
                and upload_project_count >= LV1_AUTO_PROMOTE_PROJECT_COUNT
            ):
                conn.execute(
                    "UPDATE admin_accounts SET admin_level = 2 WHERE username = ? AND admin_level < 2",
                    (admin_data["username"],),
                )
                admin_level = 2
                auto_promoted = True
                admin_data["admin_level"] = 2
                if sess_token in SESSIONS:
                    SESSIONS[sess_token]["admin_level"] = 2

            conn.commit()
            new_row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        finally:
            conn.close()

        out = self.product_row_dict(new_row)
        out["adminLevel"] = admin_level
        out["uploadProjectCount"] = upload_project_count
        out["autoPromoteTarget"] = LV1_AUTO_PROMOTE_PROJECT_COUNT
        out["autoPromoted"] = auto_promoted
        self.send_json(out)

    def handle_admin_version_rollback(self, path: str):
        admin = self.require_level2_auth()
        if not admin:
            return

        parts = [p for p in path.split("/") if p]
        if len(parts) != 5 or parts[4] != "rollback":
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        try:
            version_id = int(parts[3])
        except ValueError:
            return self.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)

        admin_level = max(1, min(3, int(admin.get("admin_level", 1))))
        publish_requires_review = False

        conn = get_db()
        try:
            begin_immediate_with_retry(conn)
            snap = conn.execute("SELECT * FROM product_versions WHERE id = ?", (version_id,)).fetchone()
            if not snap:
                conn.rollback()
                return self.send_json({"error": "version not found"}, status=HTTPStatus.NOT_FOUND)

            row = conn.execute("SELECT * FROM products WHERE id = ?", (snap["product_id"],)).fetchone()
            if not row:
                conn.rollback()
                return self.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)

            conn.execute(
                """
                INSERT INTO product_versions (
                    product_id, name, slug, version, summary, description, changelog, status,
                    file_name, file_path, file_size, file_sha256, published_at, created_at, created_by, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["name"],
                    row["slug"],
                    row["version"],
                    row["summary"],
                    row["description"],
                    row["changelog"],
                    row["status"],
                    row["file_name"],
                    row["file_path"],
                    row["file_size"],
                    row["file_sha256"],
                    row["published_at"],
                    now_iso(),
                    admin["username"],
                    "before_rollback",
                ),
            )

            target_status = snap["status"]
            target_published_at = snap["published_at"]
            if target_status == "published" and admin_level < 3:
                target_status = "draft"
                target_published_at = None
                publish_requires_review = True

            conn.execute(
                """
                UPDATE products
                SET name = ?, slug = ?, category = ?, tags = ?, announcement = ?, version = ?, summary = ?, description = ?, changelog = ?,
                    status = ?, file_name = ?, file_path = ?, file_size = ?, file_sha256 = ?,
                    published_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    snap["name"],
                    snap["slug"],
                    snap["category"],
                    snap["tags"],
                    snap["announcement"],
                    snap["version"],
                    snap["summary"],
                    snap["description"],
                    snap["changelog"],
                    target_status,
                    snap["file_name"],
                    snap["file_path"],
                    snap["file_size"],
                    snap["file_sha256"],
                    target_published_at,
                    now_iso(),
                    snap["product_id"],
                ),
            )
            conn.commit()
            new_row = conn.execute("SELECT * FROM products WHERE id = ?", (snap["product_id"],)).fetchone()
        except sqlite3.IntegrityError:
            conn.rollback()
            return self.send_json({"error": "rollback conflicts with existing slug"}, status=HTTPStatus.CONFLICT)
        finally:
            conn.close()

        out = self.product_row_dict(new_row)
        out["publish_requires_review"] = publish_requires_review
        self.send_json(out)

    def handle_download(self, path: str):
        parts = [p for p in path.split("/") if p]
        if len(parts) != 2:
            return self.send_error(HTTPStatus.NOT_FOUND)

        admin_sess = self.get_session()
        user_sess = self.get_user_session()
        if not admin_sess and not user_sess:
            return self.send_json({"error": "login required before download"}, status=HTTPStatus.UNAUTHORIZED)
        is_admin_download = admin_sess is not None
        user_id = None
        if user_sess:
            _, user_data = user_sess
            user_id = user_data["user_id"]

        key = parts[1]
        conn = get_db()
        try:
            if key.isdigit():
                if is_admin_download:
                    row = conn.execute("SELECT * FROM products WHERE id = ?", (int(key),)).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM products WHERE id = ? AND status = 'published'", (int(key),)
                    ).fetchone()
            else:
                if is_admin_download:
                    row = conn.execute("SELECT * FROM products WHERE slug = ?", (key,)).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM products WHERE slug = ? AND status = 'published'", (key,)
                    ).fetchone()
            if not row or not row["file_path"]:
                return self.send_error(HTTPStatus.NOT_FOUND)

            file_path = (BASE_DIR / row["file_path"]).resolve()
            if not file_path.exists() or not file_path.is_file():
                return self.send_error(HTTPStatus.NOT_FOUND)

            product_id = row["id"]
            if is_admin_download:
                conn.execute(
                    "INSERT INTO downloads (product_id, user_id, request_id, downloaded_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        product_id,
                        None,
                        None,
                        now_iso(),
                        self.client_address[0],
                        self.headers.get("User-Agent", ""),
                    ),
                )
                conn.commit()
            else:
                existing = conn.execute(
                    "SELECT * FROM downloads WHERE product_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
                    (product_id, user_id),
                ).fetchone()
                approved = conn.execute(
                    """
                    SELECT * FROM download_requests
                    WHERE product_id = ? AND user_id = ? AND status = 'approved' AND consumed_at IS NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    (product_id, user_id),
                ).fetchone()

                if existing and not approved:
                    return self.send_json(
                        {"error": "download quota used, submit request for additional download"},
                        status=HTTPStatus.FORBIDDEN,
                    )

                conn.execute(
                    "INSERT INTO downloads (product_id, user_id, request_id, downloaded_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        product_id,
                        user_id,
                        approved["id"] if approved else None,
                        now_iso(),
                        self.client_address[0],
                        self.headers.get("User-Agent", ""),
                    ),
                )
                if approved:
                    conn.execute(
                        "UPDATE download_requests SET consumed_at = ? WHERE id = ?",
                        (now_iso(), approved["id"]),
                    )
                conn.commit()
        finally:
            conn.close()

        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        filename = row["file_name"] or file_path.name
        with file_path.open("rb") as f:
            blob = f.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

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


def seed_if_empty() -> None:
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count > 0:
            return
        now = now_iso()
        conn.execute(
            """
            INSERT INTO products (slug, name, summary, description, category, tags, announcement, version, changelog, status, created_at, updated_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "kflow-edge-client",
                "KFlow Edge Client",
                "Secure tunneling and endpoint delivery toolkit for distributed teams.",
                "KFlow Edge Client streamlines secure endpoint publishing with low-latency routing and operational visibility.",
                "edge",
                "secure-routing,low-latency,observability",
                "Launch secure tunnels, route edge traffic, and monitor endpoint delivery in one desktop client.",
                "1.0.0",
                "Initial release",
                "published",
                now,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def call_agnes_upstream_raw(method: str, api_path: str, api_key: str, payload=None):
    base_url = "https://apihub.agnes-ai.com/v1"
    url = f"{base_url}{api_path}"
    body = None
    headers = {"Authorization": f"Bearer {api_key}"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=180) as resp:
            status = int(getattr(resp, "status", HTTPStatus.OK))
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
        ctype = (exc.headers.get("Content-Type") or "").lower()
    except URLError as exc:
        return None, {"error": "upstream unavailable", "detail": str(exc.reason)}
    except Exception as exc:
        return None, {"error": "upstream request failed", "detail": str(exc)}

    if not raw:
        return status, {}
    text = raw.decode("utf-8", errors="replace")
    if "application/json" in ctype:
        try:
            return status, json.loads(text)
        except Exception:
            return status, {"raw": text}
    return status, {"raw": text}


def is_task_not_exist_payload_raw(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    code = str(payload.get("code") or "").strip().lower()
    message = str(payload.get("message") or "").strip().lower()
    return code == "task_not_exist" or message == "task_not_exist"


def refresh_agnes_tasks_once(limit: int = 100):
    read_conn = get_db()
    try:
        rows = read_conn.execute(
            """
            SELECT t.id, t.task_id, t.api_key_id, t.status, t.model, t.prompt, t.video_url, k.api_key
            FROM agnes_video_tasks t
            LEFT JOIN agnes_api_keys k ON k.id = t.api_key_id
            WHERE t.status IN ('', 'queued', 'in_progress')
               OR (t.status = 'completed' AND (t.video_url IS NULL OR t.video_url = ''))
            ORDER BY t.updated_at ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        if not rows:
            return 0

        enabled_keys = read_conn.execute(
            "SELECT id, api_key FROM agnes_api_keys WHERE enabled = 1 ORDER BY id ASC"
        ).fetchall()
    finally:
        read_conn.close()

    updates = []
    now = now_iso()
    for row in rows:
        task_id = str(row["task_id"] or "").strip()
        if not task_id:
            continue

        status = None
        payload = None
        chosen_key_id = int(row["api_key_id"] or 0)

        # First try the bound key.
        if row["api_key"]:
            status, payload = call_agnes_upstream_raw("GET", f"/videos/{task_id}", row["api_key"])

        # Fallback scan when bound key fails or returns task_not_exist.
        need_fallback = (
            status is None
            or (status == HTTPStatus.BAD_REQUEST and is_task_not_exist_payload_raw(payload))
        )
        if need_fallback:
            for ek in enabled_keys:
                key_id = int(ek["id"])
                if key_id == chosen_key_id:
                    continue
                s, p = call_agnes_upstream_raw("GET", f"/videos/{task_id}", ek["api_key"])
                if s is None:
                    continue
                status, payload = s, p
                chosen_key_id = key_id
                if not (s == HTTPStatus.BAD_REQUEST and is_task_not_exist_payload_raw(p)):
                    break

        if status is None:
            continue

        progress_raw = payload.get("progress", 0) if isinstance(payload, dict) else 0
        try:
            progress = int(progress_raw)
        except (TypeError, ValueError):
            progress = 0
        new_status = str(payload.get("status") or "") if isinstance(payload, dict) else ""
        prev_video_url = str(row["video_url"] or "") if "video_url" in row.keys() else ""
        video_url = extract_video_url(payload) if isinstance(payload, dict) else ""
        if not video_url:
            video_url = prev_video_url
        seconds = str(payload.get("seconds") or "") if isinstance(payload, dict) else ""
        model = str(payload.get("model") or row["model"] or "") if isinstance(payload, dict) else str(row["model"] or "")
        prompt = str(payload.get("prompt") or row["prompt"] or "") if isinstance(payload, dict) else str(row["prompt"] or "")
        last_error = ""
        if isinstance(payload, dict) and (new_status == "failed" or status >= 400):
            last_error = str(payload.get("message") or payload.get("error") or payload.get("code") or "").strip()

        updates.append(
            {
                "row_id": int(row["id"]),
                "key_id": int(chosen_key_id),
                "model": model,
                "prompt": prompt,
                "status": new_status,
                "progress": progress,
                "video_url": video_url,
                "seconds": seconds,
                "last_error": last_error,
            }
        )

    if not updates:
        return 0

    write_conn = get_db()
    try:
        begin_immediate_with_retry(write_conn)
        for u in updates:
            write_conn.execute(
                """
                UPDATE agnes_video_tasks
                SET api_key_id = ?, model = ?, prompt = ?, status = ?, progress = ?, video_url = ?, seconds = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    u["key_id"],
                    u["model"],
                    u["prompt"],
                    u["status"],
                    u["progress"],
                    u["video_url"],
                    u["seconds"],
                    u["last_error"],
                    now,
                    u["row_id"],
                ),
            )
            write_conn.execute(
                "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                (now, u["key_id"]),
            )
        write_conn.commit()
        return len(updates)
    finally:
        write_conn.close()


def claim_next_agnes_chat_task():
    conn = get_db()
    try:
        begin_immediate_with_retry(conn)
        row = conn.execute(
            """
            SELECT *
            FROM agnes_chat_tasks
            WHERE status = 'queued'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.commit()
            return None
        now = now_iso()
        cur = conn.execute(
            """
            UPDATE agnes_chat_tasks
            SET status = 'in_progress',
                attempts = attempts + 1,
                started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (now, now, int(row["id"])),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return None
        if row["assistant_message_id"]:
            conn.execute(
                """
                UPDATE agnes_chat_messages
                SET status = 'in_progress', updated_at = ?
                WHERE id = ?
                """,
                (now, int(row["assistant_message_id"])),
            )
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def update_agnes_chat_task_state(
    task_row_id: int,
    assistant_message_id: int | None,
    *,
    status: str,
    content: str = "",
    thinking: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    finish_reason: str = "",
    error_text: str = "",
    api_key_id=None,
    completed: bool = False,
):
    now = now_iso()
    conn = get_db()
    try:
        params = [
            status,
            content or "",
            thinking or "",
            int(prompt_tokens or 0),
            int(completion_tokens or 0),
            int(total_tokens or 0),
            finish_reason or "",
            error_text or "",
            now,
        ]
        sql = """
            UPDATE agnes_chat_tasks
            SET status = ?,
                response_content = ?,
                response_thinking = ?,
                prompt_tokens = ?,
                completion_tokens = ?,
                total_tokens = ?,
                finish_reason = ?,
                error_text = ?,
                updated_at = ?
        """
        if api_key_id is not None:
            sql += ", api_key_id = ?"
            params.append(api_key_id)
        if completed:
            sql += ", completed_at = ?"
            params.append(now)
        sql += " WHERE id = ?"
        params.append(int(task_row_id))
        conn.execute(sql, tuple(params))
        if assistant_message_id:
            conn.execute(
                """
                UPDATE agnes_chat_messages
                SET content = ?,
                    thinking_text = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    total_tokens = ?,
                    token_source = ?,
                    status = ?,
                    error_text = ?,
                    finish_reason = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    content or "",
                    thinking or "",
                    int(prompt_tokens or 0),
                    int(completion_tokens or 0),
                    int(total_tokens or 0),
                    "upstream" if (prompt_tokens or completion_tokens or total_tokens) else "",
                    status,
                    error_text or "",
                    finish_reason or "",
                    now,
                    int(assistant_message_id),
                ),
            )
            conn.execute(
                """
                UPDATE agnes_chat_sessions
                SET updated_at = ?
                WHERE id = (
                    SELECT session_id FROM agnes_chat_messages WHERE id = ?
                )
                """,
                (now, int(assistant_message_id)),
            )
        conn.commit()
    finally:
        conn.close()


def process_agnes_chat_task(task: dict):
    task_row_id = int(task.get("id") or 0)
    assistant_message_id = int(task.get("assistant_message_id") or 0) or None
    task_id = str(task.get("task_id") or "").strip()
    raw_payload = str(task.get("request_payload") or "").strip()
    if not task_row_id or not task_id or not raw_payload:
        update_agnes_chat_task_state(
            task_row_id,
            assistant_message_id,
            status="failed",
            error_text="invalid chat task payload",
            completed=True,
        )
        return

    try:
        payload = json.loads(raw_payload)
    except Exception:
        update_agnes_chat_task_state(
            task_row_id,
            assistant_message_id,
            status="failed",
            error_text="invalid chat task payload",
            completed=True,
        )
        return

    conn = get_db()
    try:
        api_key_id, api_key = pick_agnes_chat_api_key_raw(conn)
        if not api_key:
            update_agnes_chat_task_state(
                task_row_id,
                assistant_message_id,
                status="failed",
                error_text="agnes chat api key not configured",
                completed=True,
            )
            return
        if api_key_id is not None:
            conn.execute(
                "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                (now_iso(), int(api_key_id)),
            )
            conn.commit()
    finally:
        conn.close()

    status, ctype, upstream_resp, err_payload = open_agnes_chat_upstream_stream_raw(payload, api_key=api_key)
    if status is None:
        update_agnes_chat_task_state(
            task_row_id,
            assistant_message_id,
            status="failed",
            error_text=str((err_payload or {}).get("error") or (err_payload or {}).get("detail") or "upstream unavailable"),
            api_key_id=api_key_id,
            completed=True,
        )
        return
    if upstream_resp is None:
        detail = ""
        if isinstance(err_payload, dict):
            detail = str(
                err_payload.get("error")
                or err_payload.get("detail")
                or err_payload.get("message")
                or err_payload.get("raw")
                or ""
            ).strip()
        update_agnes_chat_task_state(
            task_row_id,
            assistant_message_id,
            status="failed",
            error_text=detail or f"upstream status {status}",
            api_key_id=api_key_id,
            completed=True,
        )
        return

    final_content = ""
    final_thinking = ""
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    finish_reason = ""
    error_text = ""
    last_flush_at = 0.0

    try:
        if "text/event-stream" in (ctype or ""):
            sse_buffer = ""
            while True:
                chunk = upstream_resp.read(8192)
                if not chunk:
                    break
                sse_buffer += chunk.decode("utf-8", errors="replace")
                blocks = sse_buffer.split("\n\n")
                sse_buffer = blocks.pop() or ""
                for block in blocks:
                    parsed = parse_chat_sse_block_raw(block)
                    if not parsed:
                        continue
                    if parsed.get("error"):
                        error_text = str(parsed.get("error") or "").strip()
                    if parsed.get("content"):
                        final_content = merge_stream_text(final_content, parsed.get("content") or "")
                    if parsed.get("thinking"):
                        final_thinking = merge_stream_text(final_thinking, parsed.get("thinking") or "")
                    if parsed.get("usage"):
                        usage = parsed.get("usage") or {}
                        prompt_tokens = int(usage.get("prompt_tokens") or 0)
                        completion_tokens = int(usage.get("completion_tokens") or 0)
                        total_tokens = int(usage.get("total_tokens") or 0)
                    if parsed.get("finish_reason"):
                        finish_reason = str(parsed.get("finish_reason") or "")
                    now_ts = time.time()
                    if now_ts - last_flush_at >= 0.6:
                        update_agnes_chat_task_state(
                            task_row_id,
                            assistant_message_id,
                            status="in_progress",
                            content=final_content,
                            thinking=final_thinking,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=total_tokens,
                            finish_reason=finish_reason,
                            error_text=error_text,
                            api_key_id=api_key_id,
                        )
                        last_flush_at = now_ts
            if sse_buffer.strip():
                parsed = parse_chat_sse_block_raw(sse_buffer)
                if parsed:
                    if parsed.get("error"):
                        error_text = str(parsed.get("error") or "").strip()
                    if parsed.get("content"):
                        final_content = merge_stream_text(final_content, parsed.get("content") or "")
                    if parsed.get("thinking"):
                        final_thinking = merge_stream_text(final_thinking, parsed.get("thinking") or "")
                    if parsed.get("usage"):
                        usage = parsed.get("usage") or {}
                        prompt_tokens = int(usage.get("prompt_tokens") or 0)
                        completion_tokens = int(usage.get("completion_tokens") or 0)
                        total_tokens = int(usage.get("total_tokens") or 0)
                    if parsed.get("finish_reason"):
                        finish_reason = str(parsed.get("finish_reason") or "")
        else:
            raw = upstream_resp.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            parsed = {}
            if text:
                if "application/json" in (ctype or ""):
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = {"raw": text}
                else:
                    parsed = {"raw": text}
            if isinstance(parsed, dict):
                choice = ((parsed.get("choices") or [{}])[0]) if isinstance(parsed, dict) else {}
                message = choice.get("message", {}) if isinstance(choice, dict) else {}
                final_content = str((message or {}).get("content") or "")
                final_thinking = (
                    extract_chat_reasoning_text(message)
                    or extract_chat_reasoning_text(choice)
                    or extract_chat_reasoning_text(parsed)
                )
                usage = parsed.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or 0)
                finish_reason = str(choice.get("finish_reason") or "")
                if isinstance(parsed.get("error"), dict):
                    error_text = str(parsed.get("error", {}).get("message") or "")
                elif isinstance(parsed.get("error"), str):
                    error_text = str(parsed.get("error") or "")
            if status >= 400:
                update_agnes_chat_task_state(
                    task_row_id,
                    assistant_message_id,
                    status="failed",
                    content=final_content,
                    thinking=final_thinking,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    finish_reason=finish_reason,
                    error_text=error_text or f"upstream status {status}",
                    api_key_id=api_key_id,
                    completed=True,
                )
                return
    except Exception as exc:
        update_agnes_chat_task_state(
            task_row_id,
            assistant_message_id,
            status="failed",
            content=final_content,
            thinking=final_thinking,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
            error_text=str(exc),
            api_key_id=api_key_id,
            completed=True,
        )
        return
    finally:
        try:
            upstream_resp.close()
        except Exception:
            pass

    if not final_content.strip() and final_thinking.strip():
        final_content = "本次响应仅返回思考过程，未收到最终答复。"
    if not final_content.strip() and not final_thinking.strip():
        update_agnes_chat_task_state(
            task_row_id,
            assistant_message_id,
            status="failed",
            error_text=error_text or "stream ended without valid content",
            api_key_id=api_key_id,
            completed=True,
        )
        return

    update_agnes_chat_task_state(
        task_row_id,
        assistant_message_id,
        status="completed",
        content=final_content,
        thinking=final_thinking,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        finish_reason=finish_reason,
        error_text="",
        api_key_id=api_key_id,
        completed=True,
    )


def run_agnes_chat_task_worker(worker_name: str):
    while True:
        try:
            task = claim_next_agnes_chat_task()
            if not task:
                time.sleep(AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS)
                continue
            process_agnes_chat_task(task)
        except Exception as exc:
            print(f"[AgnesChatWorker:{worker_name}] task error: {exc}")
            time.sleep(AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS)


def run_agnes_task_worker():
    while True:
        try:
            refresh_agnes_tasks_once(limit=100)
        except Exception as exc:
            print(f"[AgnesWorker] refresh error: {exc}")
        time.sleep(AGNES_TASK_REFRESH_INTERVAL_SECONDS)


def run_db_backup_worker():
    if DB_BACKUP_INTERVAL_SECONDS <= 0:
        print("DB backup worker disabled: DB_BACKUP_INTERVAL_SECONDS <= 0")
        return
    while True:
        try:
            if should_run_db_backup():
                target = backup_database_once()
                if target is not None:
                    print(f"DB backup saved: {target.name}")
        except Exception as exc:
            print(f"[DBBackup] backup error: {exc}")
        time.sleep(DB_BACKUP_INTERVAL_SECONDS)


def refresh_agnes_chat_token_stats_once():
    now = now_iso()
    conn = get_db()
    try:
        session_rows = conn.execute(
            """
            SELECT *
            FROM agnes_chat_sessions
            ORDER BY id ASC
            """
        ).fetchall()
        owner_stats = {}
        message_updates = []

        for session_row in session_rows:
            message_rows = conn.execute(
                """
                SELECT *
                FROM agnes_chat_messages
                WHERE session_id = ?
                ORDER BY sequence_no ASC, id ASC
                """,
                (int(session_row["id"]),),
            ).fetchall()
            owner_key = str(session_row["owner_key"] or "guest:0")
            stats = owner_stats.setdefault(
                owner_key,
                {
                    "owner_key": owner_key,
                    "owner_role": session_row["owner_role"] or "guest",
                    "owner_name": session_row["owner_name"] or "guest",
                    "user_id": session_row["user_id"],
                    "session_count": 0,
                    "message_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            )
            stats["session_count"] += 1
            stats["message_count"] += len(message_rows)
            history = []
            for message_row in message_rows:
                role = str(message_row["role"] or "")
                content = str(message_row["content"] or "")
                thinking_text = str(message_row["thinking_text"] or "")
                if role == "assistant":
                    prompt_tokens = int(message_row["prompt_tokens"] or 0)
                    completion_tokens = int(message_row["completion_tokens"] or 0)
                    total_tokens = int(message_row["total_tokens"] or 0)
                    token_source = str(message_row["token_source"] or "").strip()
                    if prompt_tokens <= 0 or completion_tokens <= 0 or total_tokens <= 0:
                        prompt_tokens = estimate_prompt_tokens_for_history(session_row["system_prompt"] or "", history)
                        completion_tokens = estimate_text_tokens_value(content) + estimate_text_tokens_value(thinking_text)
                        total_tokens = prompt_tokens + completion_tokens
                        token_source = token_source or "estimated"
                        message_updates.append(
                            (prompt_tokens, completion_tokens, total_tokens, token_source, now, int(message_row["id"]))
                        )
                    elif not token_source:
                        token_source = "upstream"
                        message_updates.append(
                            (prompt_tokens, completion_tokens, total_tokens, token_source, now, int(message_row["id"]))
                        )
                    stats["input_tokens"] += prompt_tokens
                    stats["output_tokens"] += completion_tokens
                    stats["total_tokens"] += total_tokens
                history.append(
                    {
                        "role": role,
                        "content": content,
                        "thinking_text": thinking_text,
                    }
                )

        begin_immediate_with_retry(conn)
        if message_updates:
            conn.executemany(
                """
                UPDATE agnes_chat_messages
                SET prompt_tokens = ?, completion_tokens = ?, total_tokens = ?, token_source = ?, updated_at = ?
                WHERE id = ?
                """,
                message_updates,
            )
        conn.execute("DELETE FROM agnes_chat_token_stats")
        for item in owner_stats.values():
            conn.execute(
                """
                INSERT INTO agnes_chat_token_stats (
                    owner_key, owner_role, owner_name, user_id,
                    session_count, message_count, input_tokens, output_tokens, total_tokens, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["owner_key"],
                    item["owner_role"],
                    item["owner_name"],
                    item["user_id"],
                    int(item["session_count"]),
                    int(item["message_count"]),
                    int(item["input_tokens"]),
                    int(item["output_tokens"]),
                    int(item["total_tokens"]),
                    now,
                ),
            )
        conn.commit()
        SERVER_RUNTIME["chat_token_refreshed_at"] = now
        return {
            "owners": len(owner_stats),
            "messages_updated": len(message_updates),
        }
    finally:
        conn.close()


def run_chat_token_worker():
    while True:
        try:
            refresh_agnes_chat_token_stats_once()
        except Exception as exc:
            print(f"[ChatTokenWorker] refresh error: {exc}")
        time.sleep(CHAT_TOKEN_REFRESH_INTERVAL_SECONDS)


def run_server():
    init_db()
    seed_if_empty()
    try:
        refresh_agnes_chat_token_stats_once()
    except Exception as exc:
        print(f"[ChatTokenWorker] initial refresh error: {exc}")
    if should_run_db_backup():
        try:
            target = backup_database_once()
            if target is not None:
                print(f"Initial DB backup saved: {target.name}")
        except Exception as exc:
            print(f"[DBBackup] initial backup error: {exc}")
    host = os.getenv("HOST", "127.0.0.1")
    preferred_port = int(os.getenv("PORT", "49812"))
    # Windows may deny specific ports (WinError 10013) even if they look free.
    candidate_ports = [preferred_port, 8088, 8000, 0]
    # Remove duplicates while preserving order.
    candidate_ports = list(dict.fromkeys(candidate_ports))

    server = None
    last_error = None
    for port in candidate_ports:
        try:
            server = ThreadingHTTPServer((host, port), AppHandler)
            break
        except OSError as exc:
            last_error = exc
            winerror = getattr(exc, "winerror", None)
            if winerror not in (10013, 10048):
                raise
            print(f"Port {port} unavailable ({exc}). Trying next port...")

    if server is None:
        raise RuntimeError("Failed to bind server to any candidate port.") from last_error

    worker = threading.Thread(target=run_agnes_task_worker, daemon=True, name="agnes-task-worker")
    worker.start()
    chat_workers = []
    for idx in range(max(1, AGNES_CHAT_TASK_WORKER_COUNT)):
        chat_worker = threading.Thread(
            target=run_agnes_chat_task_worker,
            args=(f"chat-{idx + 1}",),
            daemon=True,
            name=f"agnes-chat-task-worker-{idx + 1}",
        )
        chat_worker.start()
        chat_workers.append(chat_worker)
    chat_token_worker = threading.Thread(target=run_chat_token_worker, daemon=True, name="agnes-chat-token-worker")
    chat_token_worker.start()
    backup_worker = threading.Thread(target=run_db_backup_worker, daemon=True, name="db-backup-worker")
    backup_worker.start()

    actual_port = server.server_address[1]
    SERVER_RUNTIME["bound_host"] = host
    SERVER_RUNTIME["bound_port"] = actual_port
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"KFlow homepage running on http://{display_host}:{actual_port}")
    print(f"Agnes task worker started: polling every {AGNES_TASK_REFRESH_INTERVAL_SECONDS}s")
    print(
        f"Agnes chat task workers started: {len(chat_workers)} threads, polling every {AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS}s"
    )
    print(f"Agnes chat token worker started: every {CHAT_TOKEN_REFRESH_INTERVAL_SECONDS}s")
    if DB_BACKUP_INTERVAL_SECONDS > 0:
        print(f"DB backup worker started: every {DB_BACKUP_INTERVAL_SECONDS}s, rotating {len(DB_BACKUP_PATHS)} copies")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
