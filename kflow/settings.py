# pyright: reportMissingImports=false
"""Django settings for KFlow."""
from __future__ import annotations

import os
from pathlib import Path

from .env import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "kflow-development-secret-change-me-please-override-in-production")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_SESSION_COOKIE = "admin_session"
try:
    LV1_AUTO_PROMOTE_PROJECT_COUNT = max(1, int(os.getenv("LV1_AUTO_PROMOTE_PROJECT_COUNT", "1")))
except ValueError:
    LV1_AUTO_PROMOTE_PROJECT_COUNT = 1
EMAIL_CODE_TTL_SECONDS = 10 * 60
EMAIL_CODE_RESEND_SECONDS = 60
EMAIL_CODE_MAX_SENDS_PER_HOUR = 5
EMAIL_CODE_MAX_ATTEMPTS = 5
EMAIL_CODE_IP_LIMIT_PER_HOUR = 20
try:
    PUBLISH_REVIEW_TIMEOUT_MINUTES = max(1, int(os.getenv("PUBLISH_REVIEW_TIMEOUT_MINUTES", "60")))
except ValueError:
    PUBLISH_REVIEW_TIMEOUT_MINUTES = 60
DEBUG = env_bool("DEBUG", False)
NEWAPI_BASE_URL = os.getenv("NEWAPI_BASE_URL", "").strip().rstrip("/")
NEWAPI_ACCESS_TOKEN = os.getenv("NEWAPI_ACCESS_TOKEN", "").strip()
NEWAPI_USER_ID = os.getenv("NEWAPI_USER_ID", "").strip()
SERVER_HOST = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
try:
    SERVER_PORT = max(1, min(65535, int(os.getenv("PORT", "9000"))))
except ValueError:
    SERVER_PORT = 9000
ALLOWED_HOSTS = [
    item.strip()
    for item in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if item.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "apps.core.apps.CoreConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.catalog.apps.CatalogConfig",
    "apps.downloads.apps.DownloadsConfig",
    "apps.points.apps.PointsConfig",
    "apps.store.apps.StoreConfig",
    "apps.publishing.apps.PublishingConfig",
    "apps.dashboard.apps.DashboardConfig",
    "apps.imaging.apps.ImagingConfig",
    "apps.forum.apps.ForumConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.LegacySessionMiddleware",
]

ROOT_URLCONF = "kflow.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]
WSGI_APPLICATION = "kflow.wsgi.application"
ASGI_APPLICATION = "kflow.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "homepage.db"))),
        "OPTIONS": {"timeout": 30},
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
PASSWORD_HASHERS = [
    "apps.accounts.hashers.LegacyHexPBKDF2PasswordHasher",
]

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "user_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_SAVE_EVERY_REQUEST = False

CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_TRUSTED_ORIGINS = [
    item.strip()
    for item in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if item.strip()
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / ".staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "kflow.storage.LenientManifestStaticFilesStorage",
    },
}
MEDIA_URL = "/uploads/"
MEDIA_ROOT = BASE_DIR / "uploads"
MATERIAL_ROOT = BASE_DIR / "Material"
CPA_BASE_URL = os.getenv("CPA_BASE_URL", "http://127.0.0.1:8317/v1").rstrip("/")
CPA_API_KEY = os.getenv("CPA_API_KEY", "").strip()
try:
    IMAGING_JOB_STALE_SECONDS = max(60, int(os.getenv("IMAGING_JOB_STALE_SECONDS", "1800")))
except ValueError:
    IMAGING_JOB_STALE_SECONDS = 1800
try:
    IMAGING_CACHE_DAYS = max(1, int(os.getenv("IMAGING_CACHE_DAYS", "30")))
except ValueError:
    IMAGING_CACHE_DAYS = 30

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("SMTP_HOST", "")
try:
    EMAIL_PORT = int(os.getenv("SMTP_PORT", "587"))
except ValueError:
    EMAIL_PORT = 587
EMAIL_HOST_USER = os.getenv("SMTP_USERNAME", "")
EMAIL_HOST_PASSWORD = os.getenv("SMTP_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("SMTP_FROM", EMAIL_HOST_USER or "webmaster@localhost")
EMAIL_USE_TLS = env_bool("SMTP_USE_TLS", True)
EMAIL_USE_SSL = env_bool("SMTP_USE_SSL", False)
try:
    EMAIL_TIMEOUT = max(1, int(os.getenv("SMTP_TIMEOUT_SECONDS", "10")))
except ValueError:
    EMAIL_TIMEOUT = 10

FILE_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
APPEND_SLASH = False
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
