"""
Configuration module (Singleton pattern).
All environment-derived constants live here, loaded once at import time.
"""
import os
import re
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
MATERIAL_DIR = BASE_DIR / "Material"
DB_PATH = DATA_DIR / "homepage.db"
DB_BACKUP_PATHS = [
    DATA_DIR / "homepage.db.backup1",
    DATA_DIR / "homepage.db.backup2",
]
STATIC_ASSET_CACHE_SECONDS = 60 * 60 * 24
VIDEO_ASSET_CACHE_SECONDS = 60 * 60 * 24 * 30
STREAM_CHUNK_SIZE = 64 * 1024


def _load_dotenv(path: Path) -> None:
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
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")

CHUNK_UPLOAD_DIR = UPLOAD_DIR / '.chunk-sessions'
CHUNK_UPLOAD_SIZE = 8 * 1024 * 1024
CHUNK_UPLOAD_TTL_SECONDS = 24 * 60 * 60

# ── Admin ──
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SESSION_TTL_SECONDS = 60 * 60 * 8

# ── Upload limits ──
LV1_UPLOAD_SIZE_LIMIT = 30 * 1024 * 1024  # 30 MB
LV2_UPLOAD_SIZE_LIMIT = 100 * 1024 * 1024
LV3_UPLOAD_SIZE_LIMIT = 100 * 1024 * 1024

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

# ── Session store (in-memory singleton) ──
SESSIONS: dict = {}

# ── Agnes key rotation ──
AGNES_KEY_ROTATION_LOCK = threading.Lock()
AGNES_KEY_ROTATION_CURSOR = 0
AGNES_TASK_REFRESH_INTERVAL_SECONDS = 10
AGNES_FREE_VIDEO_LIMIT = 5

# ── Agnes Chat ──
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

# ── Dashboard ──
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
    "system_settings",
]
DASHBOARD_MASKED_COLUMNS = {"password_hash", "api_key", "token"}

# ── Runtime state ──
SERVER_RUNTIME: dict = {
    "started_at": time.time(),
    "bound_host": "",
    "bound_port": None,
    "chat_token_refreshed_at": "",
}

# ── Chat model defaults ──
AGNES_CHAT_MODEL_CONTROL_DEFAULTS: dict = {
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
