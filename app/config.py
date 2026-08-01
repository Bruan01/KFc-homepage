"""
Configuration module (Singleton pattern).
All environment-derived constants live here, loaded once at import time.
"""
import os
import re
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

# ── User email verification / SMTP ──
def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
try:
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
except ValueError:
    SMTP_PORT = 587
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME).strip()
SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", True)
SMTP_USE_SSL = _env_bool("SMTP_USE_SSL", False)
try:
    SMTP_TIMEOUT_SECONDS = max(1, int(os.getenv("SMTP_TIMEOUT_SECONDS", "10")))
except ValueError:
    SMTP_TIMEOUT_SECONDS = 10
EMAIL_CODE_TTL_SECONDS = 10 * 60
EMAIL_CODE_RESEND_SECONDS = 60
EMAIL_CODE_MAX_SENDS_PER_HOUR = 5
EMAIL_CODE_MAX_ATTEMPTS = 5

try:
    DB_BACKUP_INTERVAL_SECONDS = max(0, int(os.getenv("DB_BACKUP_INTERVAL_SECONDS", "86400")))
except ValueError:
    DB_BACKUP_INTERVAL_SECONDS = 86400

# ── Dashboard ──
DASHBOARD_TABLE_ORDER = [
    "products",
    "product_packages",
    "product_versions",
    "downloads",
    "download_requests",
    "publish_requests",
    "publish_request_votes",
    "product_delete_requests",
    "users",
    "point_accounts",
    "point_ledger",
    "user_daily_activity",
    "download_entitlements",
    "email_verification_codes",
    "subscribers",
    "user_subscriptions",
    "admin_accounts",
    "admin_upload_events",
    "system_settings",
]
DASHBOARD_MASKED_COLUMNS = {"password", "password_hash", "code_hash", "api_key", "token"}

# ── Runtime state ──
SERVER_RUNTIME: dict = {
    "started_at": time.time(),
    "bound_host": "",
    "bound_port": None,
}
