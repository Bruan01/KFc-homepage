"""
Database schema initialization.
All DDL statements for the 20+ application tables.
"""
from datetime import datetime, timezone

from app.config import DATA_DIR, UPLOAD_DIR
from app.db import get_db
from app.utils.helpers import now_iso


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    platforms TEXT NOT NULL DEFAULT '[]',
    architectures TEXT NOT NULL DEFAULT '[]',
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
    published_at TEXT,
    point_download_cost INTEGER,
    points_redemption_enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    user_id INTEGER,
    request_id INTEGER,
    entitlement_id INTEGER,
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
    email_verified_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS point_accounts (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    total_earned INTEGER NOT NULL DEFAULT 0,
    total_spent INTEGER NOT NULL DEFAULT 0,
    contribution_score INTEGER NOT NULL DEFAULT 0,
    reputation_level INTEGER NOT NULL DEFAULT 0,
    consecutive_active_days INTEGER NOT NULL DEFAULT 0,
    last_active_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS point_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    delta INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    contribution_delta INTEGER NOT NULL DEFAULT 0,
    reference_type TEXT NOT NULL DEFAULT '',
    reference_id TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'settled',
    available_at TEXT,
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_daily_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    activity_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, activity_date),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS download_entitlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    point_ledger_id INTEGER,
    cost INTEGER NOT NULL DEFAULT 0,
    remaining_count INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    consumed_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(product_id) REFERENCES products(id),
    FOREIGN KEY(point_ledger_id) REFERENCES point_ledger(id)
);

CREATE TABLE IF NOT EXISTS email_verification_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    purpose TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    request_ip TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
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
    email TEXT NOT NULL DEFAULT '',
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

CREATE TABLE IF NOT EXISTS product_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    platform TEXT,
    architecture TEXT,
    file_name TEXT,
    file_path TEXT,
    file_size INTEGER,
    file_sha256 TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS product_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    platforms TEXT NOT NULL DEFAULT '[]',
    architectures TEXT NOT NULL DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS agnes_video_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT,
    consumed_at TEXT,
    consumed_task_id TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS agnes_video_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    api_key_id INTEGER,
    owner_key TEXT NOT NULL DEFAULT '',
    owner_role TEXT NOT NULL DEFAULT 'guest',
    owner_name TEXT NOT NULL DEFAULT 'guest',
    model TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    progress INTEGER NOT NULL DEFAULT 0,
    video_url TEXT NOT NULL DEFAULT '',
    seconds TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    is_public INTEGER NOT NULL DEFAULT 0,
    public_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(api_key_id) REFERENCES agnes_api_keys(id)
);

CREATE TABLE IF NOT EXISTS agnes_video_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_id TEXT NOT NULL,
    consumed_from TEXT NOT NULL DEFAULT 'free',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(task_id) REFERENCES agnes_video_tasks(task_id)
);

CREATE TABLE IF NOT EXISTS agnes_chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_key TEXT NOT NULL DEFAULT 'guest:0',
    owner_role TEXT NOT NULL DEFAULT 'guest',
    owner_name TEXT NOT NULL DEFAULT 'guest',
    user_id INTEGER,
    title TEXT NOT NULL DEFAULT 'New Chat',
    model TEXT NOT NULL DEFAULT 'agnes-2.0-flash',
    system_prompt TEXT NOT NULL DEFAULT '',
    enable_thinking INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agnes_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    sequence_no INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
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
    task_id TEXT NOT NULL,
    session_id INTEGER,
    user_message_id INTEGER,
    assistant_message_id INTEGER,
    owner_key TEXT NOT NULL DEFAULT 'guest:0',
    owner_role TEXT NOT NULL DEFAULT 'guest',
    owner_name TEXT NOT NULL DEFAULT 'guest',
    user_id INTEGER,
    model TEXT NOT NULL DEFAULT 'agnes-2.0-flash',
    request_payload TEXT NOT NULL DEFAULT '',
    response_content TEXT NOT NULL DEFAULT '',
    response_thinking TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    finish_reason TEXT NOT NULL DEFAULT '',
    error_text TEXT NOT NULL DEFAULT '',
    api_key_id INTEGER,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES agnes_chat_sessions(id)
);

CREATE TABLE IF NOT EXISTS agnes_chat_token_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_key TEXT NOT NULL DEFAULT 'guest:0',
    owner_role TEXT NOT NULL DEFAULT 'guest',
    owner_name TEXT NOT NULL DEFAULT 'guest',
    user_id INTEGER,
    session_count INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agnes_chat_model_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    default_model TEXT NOT NULL DEFAULT 'agnes-2.0-flash',
    default_system_prompt TEXT NOT NULL DEFAULT '',
    default_temperature REAL NOT NULL DEFAULT 0.7,
    default_max_tokens INTEGER NOT NULL DEFAULT 2048,
    default_enable_thinking INTEGER NOT NULL DEFAULT 1,
    context_window_messages INTEGER NOT NULL DEFAULT 12,
    thinking_context_window_messages INTEGER NOT NULL DEFAULT 8,
    summary_max_lines INTEGER NOT NULL DEFAULT 16,
    summary_max_chars INTEGER NOT NULL DEFAULT 1800,
    thinking_summary_max_chars INTEGER NOT NULL DEFAULT 1200,
    retain_thinking_on_empty_content INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT,
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS system_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT ''
);

-- Core table indexes (created IF NOT EXISTS for idempotency)
CREATE INDEX IF NOT EXISTS idx_products_status_updated ON products(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_downloads_product_downloaded ON downloads(product_id, downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_download_requests_user ON download_requests(user_id, status);
CREATE INDEX IF NOT EXISTS idx_point_ledger_user_time ON point_ledger(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_activity_user_date ON user_daily_activity(user_id, activity_date DESC);
CREATE INDEX IF NOT EXISTS idx_download_entitlements_user_product ON download_entitlements(user_id, product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_codes_lookup ON email_verification_codes(email, purpose, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_download_requests_status ON download_requests(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_requests_product ON publish_requests(product_id);
CREATE INDEX IF NOT EXISTS idx_publish_requests_status ON publish_requests(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_request_votes_request ON publish_request_votes(request_id);
CREATE INDEX IF NOT EXISTS idx_product_packages_product ON product_packages(product_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_product_versions_product ON product_versions(product_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_product_delete_requests_status ON product_delete_requests(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agnes_chat_sessions_owner_time ON agnes_chat_sessions(owner_key, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_uploads_product ON admin_upload_events(product_id);
CREATE INDEX IF NOT EXISTS idx_video_usage_user ON agnes_video_usage_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agnes_chat_token_stats_owner ON agnes_chat_token_stats(owner_key);

-- Performance indexes for hot queries
CREATE INDEX IF NOT EXISTS idx_downloads_user_product ON downloads(user_id, product_id);
CREATE INDEX IF NOT EXISTS idx_download_requests_product_user_status ON download_requests(product_id, user_id, status);
CREATE INDEX IF NOT EXISTS idx_email_verification_codes_email_purpose_expires ON email_verification_codes(email, purpose, expires_at);
CREATE INDEX IF NOT EXISTS idx_products_status_published ON products(status, published_at DESC);
"""


def _migrate_product_packages(conn) -> None:
    """One-time migration: copy product-level file fields into product_packages."""
    rows = conn.execute(
        "SELECT id, file_name, file_path, file_size, file_sha256 FROM products "
        "WHERE file_path IS NOT NULL AND file_path != ''"
    ).fetchall()
    if not rows:
        return
    for row in rows:
        existing = conn.execute(
            "SELECT 1 FROM product_packages WHERE product_id = ? LIMIT 1", (row["id"],)
        ).fetchone()
        if existing:
            continue
        ts = now_iso()
        conn.execute(
            """INSERT INTO product_packages
               (product_id, platform, architecture, file_name, file_path, file_size, file_sha256, sort_order, created_at, updated_at)
               VALUES (?, NULL, NULL, ?, ?, ?, ?, 0, ?, ?)""",
            (row["id"], row["file_name"], row["file_path"], row["file_size"], row["file_sha256"], ts, ts),
        )
    conn.commit()


def init_db() -> None:
    """Create all tables and ensure data / upload directories exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA_SQL)
        # Keep existing deployments compatible without rewriting historical rows.
        for table_name, columns in {
            'products': {
                'platforms': "TEXT NOT NULL DEFAULT '[]'",
                'architectures': "TEXT NOT NULL DEFAULT '[]'",
                'point_download_cost': "INTEGER",
                'points_redemption_enabled': "INTEGER NOT NULL DEFAULT 1",
            },
            'downloads': {'entitlement_id': "INTEGER"},
            'product_versions': {'platforms': "TEXT NOT NULL DEFAULT '[]'", 'architectures': "TEXT NOT NULL DEFAULT '[]'"},
            'admin_accounts': {'email': "TEXT NOT NULL DEFAULT ''"},
            'users': {'email': "TEXT NOT NULL DEFAULT ''", 'email_verified_at': "TEXT"},
        }.items():
            existing = {row['name'] for row in conn.execute(f"PRAGMA table_info({table_name})")}
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")
        # Migrate existing product files → product_packages (one-time, idempotent)
        _migrate_product_packages(conn)

        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_accounts_email_unique "
            "ON admin_accounts(email) WHERE email <> ''"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_verified_email_unique "
            "ON users(lower(email)) WHERE email <> '' AND email_verified_at IS NOT NULL"
        )
        # Idempotent launch grant for all verified historical users. New registrations
        # use the same key, so startup can never double-award the registration bonus.
        verified_users = conn.execute(
            "SELECT id FROM users WHERE email_verified_at IS NOT NULL"
        ).fetchall()
        for user in verified_users:
            user_id = int(user['id'])
            created_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO point_accounts (user_id, updated_at) VALUES (?, ?)",
                (user_id, created_at),
            )
            key = f"registration_reward:{user_id}"
            if not conn.execute("SELECT 1 FROM point_ledger WHERE idempotency_key = ?", (key,)).fetchone():
                account = conn.execute("SELECT * FROM point_accounts WHERE user_id = ?", (user_id,)).fetchone()
                balance = int(account['balance'] or 0) + 20
                contribution = int(account['contribution_score'] or 0) + 10
                conn.execute(
                    "UPDATE point_accounts SET balance = ?, total_earned = total_earned + 20, "
                    "contribution_score = ?, updated_at = ? WHERE user_id = ?",
                    (balance, contribution, created_at, user_id),
                )
                conn.execute(
                    "INSERT INTO point_ledger (user_id, event_type, delta, balance_after, contribution_delta, "
                    "reference_type, reference_id, idempotency_key, description, created_by, created_at) "
                    "VALUES (?, 'registration_reward', 20, ?, 10, 'user', ?, ?, '邮箱验证注册奖励', 'system', ?)",
                    (user_id, balance, str(user_id), key, created_at),
                )
        conn.commit()
    finally:
        conn.close()
