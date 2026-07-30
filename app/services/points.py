"""Transactional K-points ledger, daily activity and download redemption rules."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.utils.helpers import now_iso

SITE_TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_RULES = {
    "registration_reward": 20,
    "registration_contribution": 10,
    "daily_activity_reward": 2,
    "daily_activity_contribution": 1,
    "download_default_cost": 10,
    "download_entitlement_ttl_hours": 24,
    "download_redemption_enabled": True,
}

SETTING_KEYS = {
    "registration_reward": "points.registration.reward",
    "registration_contribution": "points.registration.contribution",
    "daily_activity_reward": "points.daily_activity.reward",
    "daily_activity_contribution": "points.daily_activity.contribution",
    "download_default_cost": "points.download.default_cost",
    "download_entitlement_ttl_hours": "points.download.entitlement_ttl_hours",
    "download_redemption_enabled": "points.download.redemption_enabled",
}


class PointsError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _setting(conn, name, default):
    row = conn.execute(
        "SELECT setting_value FROM system_settings WHERE setting_key = ?", (SETTING_KEYS[name],)
    ).fetchone()
    if not row:
        return default
    raw = row["setting_value"]
    if isinstance(default, bool):
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_rules(conn):
    rules = {name: _setting(conn, name, default) for name, default in DEFAULT_RULES.items()}
    rules["registration_reward"] = max(0, rules["registration_reward"])
    rules["registration_contribution"] = max(0, rules["registration_contribution"])
    rules["daily_activity_reward"] = max(0, rules["daily_activity_reward"])
    rules["daily_activity_contribution"] = max(0, rules["daily_activity_contribution"])
    rules["download_default_cost"] = max(0, rules["download_default_cost"])
    rules["download_entitlement_ttl_hours"] = max(1, rules["download_entitlement_ttl_hours"])
    return rules


def save_rules(conn, values, updated_by: str):
    rules = get_rules(conn)
    for name, default in DEFAULT_RULES.items():
        if name not in values:
            continue
        if isinstance(default, bool):
            value = bool(values[name])
            stored = "true" if value else "false"
        else:
            try:
                value = int(values[name])
            except (TypeError, ValueError):
                raise PointsError(f"invalid rule: {name}")
            if value < 0:
                raise PointsError(f"rule must be non-negative: {name}")
            if name == "download_entitlement_ttl_hours" and value < 1:
                raise PointsError("download entitlement TTL must be at least 1 hour")
            stored = str(value)
        conn.execute(
            "INSERT INTO system_settings (setting_key, setting_value, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(setting_key) DO UPDATE SET "
            "setting_value = excluded.setting_value, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (SETTING_KEYS[name], stored, now_iso(), updated_by),
        )
    return get_rules(conn)


def ensure_account(conn, user_id: int):
    conn.execute(
        "INSERT OR IGNORE INTO point_accounts (user_id, updated_at) VALUES (?, ?)",
        (int(user_id), now_iso()),
    )
    return conn.execute("SELECT * FROM point_accounts WHERE user_id = ?", (int(user_id),)).fetchone()


def apply_ledger(
    conn,
    *,
    user_id: int,
    event_type: str,
    points_delta: int,
    contribution_delta: int = 0,
    idempotency_key: str,
    description: str = "",
    reference_type: str = "",
    reference_id: str = "",
    created_by: str = "system",
):
    existing = conn.execute(
        "SELECT * FROM point_ledger WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    if existing:
        return existing, False
    account = ensure_account(conn, user_id)
    if account["status"] != "active":
        raise PointsError("points account frozen", 403)
    points_delta = int(points_delta)
    contribution_delta = int(contribution_delta)
    balance = int(account["balance"] or 0) + points_delta
    if balance < 0:
        raise PointsError("insufficient points", 409)
    contribution = max(0, int(account["contribution_score"] or 0) + contribution_delta)
    created_at = now_iso()
    conn.execute(
        "UPDATE point_accounts SET balance = ?, total_earned = total_earned + ?, "
        "total_spent = total_spent + ?, contribution_score = ?, updated_at = ? WHERE user_id = ?",
        (balance, max(0, points_delta), max(0, -points_delta), contribution, created_at, user_id),
    )
    cursor = conn.execute(
        "INSERT INTO point_ledger (user_id, event_type, delta, balance_after, contribution_delta, "
        "reference_type, reference_id, idempotency_key, description, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            event_type,
            points_delta,
            balance,
            contribution_delta,
            reference_type or "",
            str(reference_id or ""),
            idempotency_key,
            description or "",
            created_by or "system",
            created_at,
        ),
    )
    return conn.execute("SELECT * FROM point_ledger WHERE id = ?", (cursor.lastrowid,)).fetchone(), True


def award_registration(conn, user_id: int):
    rules = get_rules(conn)
    return apply_ledger(
        conn,
        user_id=user_id,
        event_type="registration_reward",
        points_delta=rules["registration_reward"],
        contribution_delta=rules["registration_contribution"],
        idempotency_key=f"registration_reward:{user_id}",
        description="邮箱验证注册奖励",
        reference_type="user",
        reference_id=str(user_id),
    )


def award_daily_activity(conn, user_id: int):
    activity_date = datetime.now(SITE_TZ).date().isoformat()
    try:
        conn.execute(
            "INSERT INTO user_daily_activity (user_id, activity_date, created_at) VALUES (?, ?, ?)",
            (user_id, activity_date, now_iso()),
        )
    except sqlite3.IntegrityError:
        return None, False
    rules = get_rules(conn)
    ledger, created = apply_ledger(
        conn,
        user_id=user_id,
        event_type="daily_activity",
        points_delta=rules["daily_activity_reward"],
        contribution_delta=rules["daily_activity_contribution"],
        idempotency_key=f"daily_activity:{user_id}:{activity_date}",
        description="每日首次有效访问",
        reference_type="activity_date",
        reference_id=activity_date,
    )
    conn.execute(
        "UPDATE point_accounts SET last_active_date = ?, updated_at = ? WHERE user_id = ?",
        (activity_date, now_iso(), user_id),
    )
    return ledger, created


def account_payload(conn, user_id: int):
    account = ensure_account(conn, user_id)
    return {
        "balance": int(account["balance"] or 0),
        "totalEarned": int(account["total_earned"] or 0),
        "totalSpent": int(account["total_spent"] or 0),
        "contributionScore": int(account["contribution_score"] or 0),
        "reputationLevel": int(account["reputation_level"] or 0),
        "status": account["status"],
        "lastActiveDate": account["last_active_date"] or "",
    }


def product_download_cost(conn, product):
    rules = get_rules(conn)
    if not rules["download_redemption_enabled"] or not bool(product["points_redemption_enabled"]):
        return None
    value = product["point_download_cost"]
    return rules["download_default_cost"] if value is None else max(0, int(value))


def active_entitlement(conn, user_id: int, product_id: int):
    return conn.execute(
        "SELECT * FROM download_entitlements WHERE user_id = ? AND product_id = ? "
        "AND remaining_count > 0 AND consumed_at IS NULL AND (expires_at IS NULL OR expires_at > ?) "
        "ORDER BY id DESC LIMIT 1",
        (user_id, product_id, now_iso()),
    ).fetchone()


def redeem_download(conn, *, user_id: int, product_id: int, idempotency_key: str):
    idem = (idempotency_key or "").strip()
    if len(idem) < 8 or len(idem) > 160:
        raise PointsError("valid idempotency key required")
    existing_redemption = conn.execute(
        "SELECT * FROM download_entitlements WHERE idempotency_key = ?", (idem,)
    ).fetchone()
    if existing_redemption:
        if int(existing_redemption["user_id"]) != int(user_id):
            raise PointsError("idempotency key conflict", 409)
        return existing_redemption, account_payload(conn, user_id), False

    product = conn.execute(
        "SELECT * FROM products WHERE id = ? AND status = 'published'", (product_id,)
    ).fetchone()
    if not product:
        raise PointsError("published product not found", 404)
    file_exists = bool(product["file_path"]) or bool(
        conn.execute(
            "SELECT 1 FROM product_packages WHERE product_id = ? AND file_path <> '' LIMIT 1", (product_id,)
        ).fetchone()
    )
    if not file_exists:
        raise PointsError("product file unavailable", 409)
    if not conn.execute(
        "SELECT 1 FROM downloads WHERE product_id = ? AND user_id = ? LIMIT 1", (product_id, user_id)
    ).fetchone():
        raise PointsError("free download still available", 409)
    if conn.execute(
        "SELECT 1 FROM download_requests WHERE product_id = ? AND user_id = ? "
        "AND status = 'approved' AND consumed_at IS NULL LIMIT 1",
        (product_id, user_id),
    ).fetchone():
        raise PointsError("approved download already available", 409)
    active = active_entitlement(conn, user_id, product_id)
    if active:
        raise PointsError("unused download entitlement already exists", 409)
    cost = product_download_cost(conn, product)
    if cost is None:
        raise PointsError("points redemption disabled for product", 403)
    ledger, _ = apply_ledger(
        conn,
        user_id=user_id,
        event_type="download_redemption",
        points_delta=-cost,
        idempotency_key=f"download_redemption:{idem}",
        description=f"兑换产品额外下载：{product['name']}",
        reference_type="product",
        reference_id=str(product_id),
    )
    rules = get_rules(conn)
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=rules["download_entitlement_ttl_hours"])
    cursor = conn.execute(
        "INSERT INTO download_entitlements (user_id, product_id, source, point_ledger_id, cost, "
        "remaining_count, idempotency_key, created_at, expires_at) VALUES (?, ?, 'points', ?, ?, 1, ?, ?, ?)",
        (user_id, product_id, ledger["id"], cost, idem, created_at.isoformat(), expires_at.isoformat()),
    )
    entitlement = conn.execute(
        "SELECT * FROM download_entitlements WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return entitlement, account_payload(conn, user_id), True


def ledger_payload(row):
    return {
        "id": row["id"],
        "eventType": row["event_type"],
        "delta": int(row["delta"]),
        "balanceAfter": int(row["balance_after"]),
        "contributionDelta": int(row["contribution_delta"] or 0),
        "referenceType": row["reference_type"] or "",
        "referenceId": row["reference_id"] or "",
        "description": row["description"] or "",
        "status": row["status"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
    }
