"""
User authentication handlers — login, logout, me, account.
"""
import secrets
import time
from http import HTTPStatus

from app.config import USER_SESSION_COOKIE, SESSION_TTL_SECONDS, SESSIONS
from app.db import get_db
from app.utils.crypto import hash_password, verify_password
from app.utils.helpers import now_iso


def handle_user_login(handler):
    """POST /api/user/login — login or auto-register."""
    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    if not username or not password:
        handler.send_json({"error": "credentials required"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            # 新用户：直接存哈希
            pw_hash = hash_password(password)
            conn.execute(
                "INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                (username, pw_hash, now_iso()),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        else:
            # 已有用户：确认密码
            if not verify_password(password, row["password"]):
                handler.send_json({"error": "invalid credentials"}, status=HTTPStatus.UNAUTHORIZED)
                return
            # 明文密码迁移：如果是旧版明文，自动升级为哈希
            stored = row["password"] or ""
            if not stored.startswith("pbkdf2_sha256$"):
                pw_hash = hash_password(password)
                conn.execute(
                    "UPDATE users SET password = ? WHERE id = ?",
                    (pw_hash, row["id"]),
                )
                conn.commit()
    finally:
        conn.close()

    token = secrets.token_hex(32)
    SESSIONS[token] = {
        "username": row["username"],
        "user_id": row["id"],
        "role": "user",
        "exp": time.time() + SESSION_TTL_SECONDS,
    }
    handler.send_json({"token": token, "username": row["username"], "user_id": row["id"]})


def handle_user_logout(handler):
    """POST /api/user/logout"""
    cookies = handler.parse_cookies()
    token = cookies.get(USER_SESSION_COOKIE)
    if token:
        SESSIONS.pop(token, None)
    handler.send_json({"ok": True})


def handle_user_me(handler):
    """GET /api/user/me"""
    sess = handler.get_user_session()
    if not sess:
        handler.send_json({"loggedIn": False})
        return
    _, data = sess
    handler.send_json({"loggedIn": True, "username": data["username"], "user_id": data["user_id"]})


def handle_account_me(handler):
    """GET /api/account/me — unified account info (user/admin/guest)."""
    user_sess = handler.get_user_session()
    if user_sess:
        _, user = user_sess
        handler.send_json(
            {
                "loggedIn": True,
                "role": "user",
                "username": user.get("username", ""),
                "user_id": user.get("user_id"),
            }
        )
        return
    admin_sess = handler.get_session()
    if admin_sess:
        _, admin = admin_sess
        handler.send_json(
            {
                "loggedIn": True,
                "role": "admin",
                "username": admin.get("username", ""),
                "adminLevel": int(admin.get("admin_level", 1)),
                "isSuper": bool(admin.get("is_super")),
            }
        )
        return
    handler.send_json({"loggedIn": False, "role": "guest"})
