"""
User authentication handlers — login, logout, me, account.
"""
import json
import secrets
import time
from http import HTTPStatus

from app.config import USER_SESSION_COOKIE, SESSION_TTL_SECONDS, SESSIONS
from app.db import get_db
from app.utils.crypto import hash_password, verify_password
from app.utils.helpers import now_iso


def _send_json_with_cookie(handler, payload, token):
    """Send JSON response with Set-Cookie header."""
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Set-Cookie", f"{USER_SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
    handler.end_headers()
    handler.wfile.write(blob)


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
    _send_json_with_cookie(handler, {"token": token, "username": row["username"], "user_id": row["id"]}, token)


def handle_user_logout(handler):
    """POST /api/user/logout"""
    cookies = handler.parse_cookies()
    token = cookies.get(USER_SESSION_COOKIE)
    if token:
        SESSIONS.pop(token, None)
    blob = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Set-Cookie", f"{USER_SESSION_COOKIE}=deleted; Path=/; Max-Age=0; SameSite=Lax")
    handler.end_headers()
    handler.wfile.write(blob)


def handle_user_me(handler):
    """GET /api/user/me"""
    sess = handler.get_user_session()
    if not sess:
        handler.send_json({"loggedIn": False})
        return
    _, data = sess
    handler.send_json({"loggedIn": True, "username": data["username"], "user_id": data["user_id"]})


def handle_account_me(handler):
    """GET /api/account/me — unified account info (admin/user/guest).

    1. Check admin_session cookie first
    2. If not found, try user_session cookie
    3. Fallback: if username looks like an admin (e.g. 'admin'), treat as admin
    """
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
    user_sess = handler.get_user_session()
    if user_sess:
        _, user = user_sess
        # Fallback: check if this user exists in admin_accounts or matches ADMIN_USERNAME
        # (covers case where admin_session cookie was lost but user_session remains)
        _username = user.get("username", "")
        from app.config import ADMIN_USERNAME as _ADMIN_USERNAME
        if _username == _ADMIN_USERNAME:
            handler.send_json(
                {
                    "loggedIn": True,
                    "role": "admin",
                    "username": _username,
                    "adminLevel": 3,
                    "isSuper": True,
                }
            )
            return
        from app.db import get_db as _get_db
        _conn = _get_db()
        try:
            _admin_row = _conn.execute(
                "SELECT admin_level, is_super FROM admin_accounts WHERE username = ?",
                (_username,),
            ).fetchone()
        finally:
            _conn.close()
        if _admin_row:
            handler.send_json(
                {
                    "loggedIn": True,
                    "role": "admin",
                    "username": _username,
                    "adminLevel": int(_admin_row["admin_level"] or 1),
                    "isSuper": bool(_admin_row["is_super"]),
                }
            )
            return
        handler.send_json(
            {
                "loggedIn": True,
                "role": "user",
                "username": user.get("username", ""),
                "user_id": user.get("user_id"),
            }
        )
        return
    handler.send_json({"loggedIn": False, "role": "guest"})
