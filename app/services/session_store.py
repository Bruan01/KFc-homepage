"""
Persistent session store backed by SQLite.

Replaces the in-memory SESSIONS dict so sessions survive process restarts.
All session operations (create/get/delete) go through this module.
"""
import threading
import time
from typing import Optional

from app.db import get_db
from app.utils.helpers import now_iso

_lock = threading.Lock()


def _now_ts() -> float:
    return time.time()


def session_create(
    token: str,
    role: str,
    username: str,
    exp: float,
    user_id: Optional[int] = None,
    admin_level: Optional[int] = None,
    is_super: bool = False,
    created_ip: str = "",
) -> None:
    """Insert a new session record."""
    now = now_iso()
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO sessions
               (token, role, user_id, username, admin_level, is_super, created_ip, last_seen_ip, exp, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                token,
                role,
                user_id,
                username,
                admin_level,
                1 if is_super else 0,
                created_ip,
                created_ip,
                exp,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def session_get(token: str) -> Optional[dict]:
    """Look up a session by token. Returns None if missing or expired."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token = ? LIMIT 1", (token,)
        ).fetchone()
        if not row:
            return None
        if row["exp"] < _now_ts():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return {
            "token": row["token"],
            "role": row["role"],
            "user_id": row["user_id"],
            "username": row["username"],
            "admin_level": row["admin_level"],
            "is_super": bool(row["is_super"]),
            "exp": row["exp"],
            "created_ip": row["created_ip"],
            "last_seen_ip": row["last_seen_ip"],
        }
    finally:
        conn.close()


def session_touch(token: str, ip: str = "") -> None:
    """Update last_seen_ip and extend TTL (optional)."""
    now = now_iso()
    conn = get_db()
    try:
        conn.execute(
            "UPDATE sessions SET last_seen_ip = ?, updated_at = ? WHERE token = ?",
            (ip, now, token),
        )
        conn.commit()
    finally:
        conn.close()


def session_delete(token: str) -> None:
    """Remove a session."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def session_delete_all_for_user(user_id: int) -> None:
    """Remove all sessions for a user (e.g., password change)."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def cleanup_expired_sessions() -> int:
    """Delete all expired sessions. Returns count removed."""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM sessions WHERE exp < ?", (_now_ts(),))
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def list_active_sessions() -> list:
    """Return all non-expired sessions for dashboard."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE exp >= ? ORDER BY updated_at DESC",
            (_now_ts(),),
        ).fetchall()
        return [
            {
                "token": r["token"],
                "role": r["role"],
                "user_id": r["user_id"],
                "username": r["username"],
                "admin_level": r["admin_level"],
                "is_super": bool(r["is_super"]),
                "exp": r["exp"],
                "created_ip": r["created_ip"],
                "last_seen_ip": r["last_seen_ip"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()