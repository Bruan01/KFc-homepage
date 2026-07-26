"""
Admin authentication handlers — login, logout, me, register, tokens.
"""
import json
import secrets
import time
from http import HTTPStatus
from urllib.parse import urlparse

from app.config import ADMIN_PASSWORD, ADMIN_SESSION_COOKIE, ADMIN_USERNAME, EMAIL_RE, SESSION_TTL_SECONDS, SESSIONS
from app.db import get_db
from app.utils.upload_limits import get_upload_limit_settings
from app.utils.crypto import hash_password, verify_password
from app.utils.helpers import now_iso


def handle_admin_login(handler):
    """POST /api/admin/login — sets session cookie for browser."""
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

    token = None
    session_data = None

    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = secrets.token_hex(32)
        session_data = {
            "username": ADMIN_USERNAME,
            "is_super": True,
            "admin_level": 3,
            "role": "admin",
            "exp": time.time() + SESSION_TTL_SECONDS,
        }
    else:
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM admin_accounts WHERE username = ?", (username,)).fetchone()
        finally:
            conn.close()

        if not row:
            handler.send_json({"error": "invalid credentials"}, status=HTTPStatus.UNAUTHORIZED)
            return
        if not verify_password(password, row["password_hash"]):
            handler.send_json({"error": "invalid credentials"}, status=HTTPStatus.UNAUTHORIZED)
            return
        token = secrets.token_hex(32)
        session_data = {
            "username": row["username"],
            "is_super": bool(row["is_super"]),
            "admin_level": int(row["admin_level"]),
            "role": "admin",
            "exp": time.time() + SESSION_TTL_SECONDS,
        }

    SESSIONS[token] = session_data

    # Build JSON response with Set-Cookie header (required for admin-login.html)
    payload = {
        "token": token,
        "username": session_data["username"],
        "is_super": session_data["is_super"],
        "admin_level": session_data["admin_level"],
    }
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
    handler.end_headers()
    handler.wfile.write(blob)


def handle_admin_logout(handler):
    """POST /api/admin/logout"""
    cookies = handler.parse_cookies()
    token = cookies.get(ADMIN_SESSION_COOKIE)
    if token:
        SESSIONS.pop(token, None)
    # Send Set-Cookie to clear the cookie in browser
    blob = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}=deleted; Path=/; Max-Age=0; SameSite=Lax")
    handler.end_headers()
    handler.wfile.write(blob)


def handle_admin_me(handler):
    """GET /api/admin/me"""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"loggedIn": False})
        return
    _, data = sess
    upload_project_count = 0
    upload_settings = None
    if not bool(data.get("is_super")):
        conn = get_db()
        try:
            upload_project_count = conn.execute(
                "SELECT COUNT(*) FROM admin_upload_events WHERE admin_username = ?",
                (data["username"],),
            ).fetchone()[0]
            upload_settings = get_upload_limit_settings(conn)
        finally:
            conn.close()
    else:
        upload_settings = get_upload_limit_settings()
    from app.config import LV1_AUTO_PROMOTE_PROJECT_COUNT
    handler.send_json(
        {
            "loggedIn": True,
            "username": data["username"],
            "isSuper": bool(data.get("is_super")),
            "adminLevel": int(data.get("admin_level", 1)),
            "uploadProjectCount": upload_project_count,
            "autoPromoteTarget": LV1_AUTO_PROMOTE_PROJECT_COUNT,
            "uploadSettings": upload_settings or get_upload_limit_settings(),
        }
    )


def handle_admin_register(handler):
    """POST /api/admin/register — register using a one-time token."""
    sess = handler.get_session()
    if sess:
        handler.send_json({"error": "already logged in"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return

    token = (body.get("token") or "").strip()
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    email = (body.get("email") or "").strip().lower()
    if not token or not username or not password or not email:
        handler.send_json({"error": "token, username, password and email required"}, status=HTTPStatus.BAD_REQUEST)
        return
    if not EMAIL_RE.match(email):
        handler.send_json({"error": "invalid email format"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM admin_register_tokens WHERE token = ? AND used_by_admin_id IS NULL",
            (token,),
        ).fetchone()
        if not row:
            handler.send_json({"error": "invalid or already used token"}, status=HTTPStatus.BAD_REQUEST)
            return
        existing = conn.execute("SELECT id FROM admin_accounts WHERE username = ?", (username,)).fetchone()
        if existing:
            handler.send_json({"error": "username already exists"}, status=HTTPStatus.CONFLICT)
            return
        email_owner = conn.execute("SELECT id FROM admin_accounts WHERE email = ?", (email,)).fetchone()
        if email_owner:
            handler.send_json({"error": "email already exists"}, status=HTTPStatus.CONFLICT)
            return

        pw_hash = hash_password(password)
        cur = conn.execute(
            """
            INSERT INTO admin_accounts (username, password_hash, email, created_at, created_by, is_super, admin_level)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (username, pw_hash, email, now_iso(), row["created_by"], int(row["admin_level"])),
        )
        admin_id = cur.lastrowid
        conn.execute(
            "UPDATE admin_register_tokens SET used_by_admin_id = ?, used_at = ? WHERE id = ?",
            (admin_id, now_iso(), row["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    handler.send_json({"ok": True, "username": username, "email": email, "adminLevel": int(row["admin_level"])})


def handle_admin_tokens_get(handler):
    """GET /api/admin/tokens — list registration tokens."""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM admin_register_tokens ORDER BY id DESC LIMIT 200"
        ).fetchall()
        items = [
            {
                "id": r["id"],
                "token": r["token"][:8] + "..." if r["token"] else "",
                "created_by": r["created_by"],
                "created_at": r["created_at"],
                "admin_level": int(r["admin_level"]),
                "used": r["used_by_admin_id"] is not None,
            }
            for r in rows
        ]
    finally:
        conn.close()
    handler.send_json({"items": items})


def handle_admin_tokens_create(handler):
    """POST /api/admin/tokens — create a registration token."""
    sess = handler.require_level2_auth()
    if not sess:
        return
    admin = sess
    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return
    level = 1
    if "admin_level" in body:
        try:
            level = max(1, min(3, int(body["admin_level"])))
        except (TypeError, ValueError):
            pass

    token = secrets.token_hex(32)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO admin_register_tokens (token, created_by, created_at, admin_level) VALUES (?, ?, ?, ?)",
            (token, admin["username"], now_iso(), level),
        )
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True, "token": token, "admin_level": level})


def handle_admin_users_get(handler):
    """GET /api/admin/users — list all users with download stats."""
    if not handler.require_auth():
        return
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT
                u.id, u.username, u.email, u.created_at,
                COUNT(DISTINCT d.id) AS download_count,
                COUNT(DISTINCT dr.id) AS request_count,
                CASE WHEN us.id IS NOT NULL THEN 1 ELSE 0 END AS is_subscribed
            FROM users u
            LEFT JOIN downloads d ON d.user_id = u.id
            LEFT JOIN download_requests dr ON dr.user_id = u.id
            LEFT JOIN user_subscriptions us ON us.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    items = [
        {
            "id": r["id"],
            "username": r["username"] or "",
            "email": r["email"] or "",
            "created_at": r["created_at"],
            "download_count": int(r["download_count"] or 0),
            "request_count": int(r["request_count"] or 0),
            "is_subscribed": bool(r["is_subscribed"]),
        }
        for r in rows
    ]
    handler.send_json({"items": items})
