"""User authentication handlers — verified registration, three login modes and email binding."""
import json
import secrets
import sqlite3
import time
from http import HTTPStatus

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_SESSION_COOKIE,
    ADMIN_USERNAME,
    EMAIL_RE,
    SESSION_TTL_SECONDS,
    SESSIONS,
    USER_SESSION_COOKIE,
)
from app.db import begin_immediate_with_retry, get_db
from app.services.points import PointsError, award_daily_activity, award_registration
from app.services.email_auth import (
    EmailCodeError,
    consume_verification_code,
    issue_verification_code,
    mask_email,
    normalize_email,
)
from app.utils.crypto import hash_password, verify_password
from app.utils.helpers import now_iso


def _read_body(handler):
    try:
        return handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return None



def _start_user_session(handler, row):
    """Create a user session and, if the user is also an admin, also create an admin session."""
    token = secrets.token_urlsafe(32)
    exp = time.time() + SESSION_TTL_SECONDS
    SESSIONS[token] = {
        "username": row["username"],
        "user_id": row["id"],
        "role": "user",
        "registration_verified": True,
        "exp": exp,
    }
    # Daily-activity reward on successful login — keeps the read-hot `/me`
    # endpoints from taking a write lock on every poll.
    _award_daily_for_session({"user_id": row["id"]})

    # If this user is also an admin, create an admin session too (unified login)
    admin_token = None
    admin_payload = {}
    if row["username"] == ADMIN_USERNAME:
        admin_token = secrets.token_hex(32)
        SESSIONS[admin_token] = {
            "username": ADMIN_USERNAME,
            "is_super": True,
            "admin_level": 3,
            "role": "admin",
            "exp": exp,
        }
        admin_payload = {"is_admin": True, "is_super": True, "admin_level": 3}
    else:
        conn = get_db()
        try:
            admin_row = conn.execute(
                "SELECT * FROM admin_accounts WHERE username = ?", (row["username"],)
            ).fetchone()
        finally:
            conn.close()
        if admin_row:
            admin_token = secrets.token_hex(32)
            SESSIONS[admin_token] = {
                "username": admin_row["username"],
                "is_super": bool(admin_row["is_super"]),
                "admin_level": int(admin_row["admin_level"]),
                "role": "admin",
                "exp": exp,
            }
            admin_payload = {
                "is_admin": True,
                "is_super": bool(admin_row["is_super"]),
                "admin_level": int(admin_row["admin_level"]),
            }

    payload = {
        "ok": True,
        "token": token,
        "username": row["username"],
        "user_id": row["id"],
        **admin_payload,
    }
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Set-Cookie", f"{USER_SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
    if admin_token:
        handler.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}={admin_token}; HttpOnly; Path=/; SameSite=Lax")
    handler.end_headers()
    handler.wfile.write(blob)


def _start_admin_only_session(handler, username, is_super, admin_level):
    """Create an admin session for legacy/admin-only identities using the unified login endpoint."""
    token = secrets.token_hex(32)
    SESSIONS[token] = {
        "username": username,
        "is_super": bool(is_super),
        "admin_level": int(admin_level),
        "role": "admin",
        "exp": time.time() + SESSION_TTL_SECONDS,
    }
    payload = {
        "ok": True,
        "token": token,
        "username": username,
        "role": "admin",
        "is_admin": True,
        "is_super": bool(is_super),
        "admin_level": int(admin_level),
    }
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
    handler.end_headers()
    handler.wfile.write(blob)


def _find_admin_credentials(conn, username, password):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        return {"username": ADMIN_USERNAME, "is_super": True, "admin_level": 3}
    row = conn.execute("SELECT * FROM admin_accounts WHERE username = ?", (username,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return {
        "username": row["username"],
        "is_super": bool(row["is_super"]),
        "admin_level": int(row["admin_level"]),
    }


def _email_payload(row):
    verified = bool(row and row["email"] and row["email_verified_at"])
    return {
        "emailMasked": mask_email(row["email"]) if verified else "",
        "hasVerifiedEmail": verified,
    }


def _find_user_by_session(session_data):
    conn = get_db()
    return conn.execute(
        "SELECT id, username, password, email, email_verified_at FROM users WHERE id = ?",
        (session_data.get("user_id"),),
    ).fetchone()


def handle_user_verification_code(handler):
    """POST /api/user/verification-code."""
    body = _read_body(handler)
    if body is None:
        return
    email = normalize_email(body.get("email"))
    purpose = (body.get("purpose") or "").strip().lower()
    if purpose == "bind":
        sess = handler.get_user_session()
        if not sess:
            handler.send_json({"error": "login required"}, status=HTTPStatus.UNAUTHORIZED)
            return
        row = _find_user_by_session(sess[1])
        if not row:
            handler.send_json({"error": "account not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if row["email"] and row["email_verified_at"]:
            handler.send_json({"error": "verified email already bound"}, status=HTTPStatus.CONFLICT)
            return
        owner = get_db().execute(
            "SELECT id FROM users WHERE lower(email) = ? AND email_verified_at IS NOT NULL AND id <> ? LIMIT 1",
            (email, row["id"]),
        ).fetchone()
        if owner:
            handler.send_json({"error": "email already registered"}, status=HTTPStatus.CONFLICT)
            return
    try:
        issue_verification_code(email, purpose, handler.client_address[0] if handler.client_address else "")
    except EmailCodeError as exc:
        handler.send_json({"error": exc.message}, status=exc.status)
        return
    # Login deliberately returns the same response even when no matching account exists.
    handler.send_json({"ok": True, "message": "If the email is eligible, a verification code has been sent."})


def handle_user_register(handler):
    """POST /api/user/register — explicit verified registration."""
    body = _read_body(handler)
    if body is None:
        return
    username = (body.get("username") or "").strip()
    email = normalize_email(body.get("email"))
    password = body.get("password") or ""
    code = (body.get("code") or "").strip()
    invite_code = (body.get("inviteCode") or body.get("invite_code") or "").strip()
    if not 3 <= len(username) <= 64:
        handler.send_json({"error": "username must be 3-64 characters"}, status=HTTPStatus.BAD_REQUEST)
        return
    if not EMAIL_RE.fullmatch(email):
        handler.send_json({"error": "invalid email format"}, status=HTTPStatus.BAD_REQUEST)
        return
    if len(password) < 8:
        handler.send_json({"error": "password must be at least 8 characters"}, status=HTTPStatus.BAD_REQUEST)
        return
    if not code:
        handler.send_json({"error": "verification code required"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    begin_immediate_with_retry(conn)
    try:
        if username == ADMIN_USERNAME or conn.execute(
            "SELECT 1 FROM admin_accounts WHERE username = ? LIMIT 1", (username,)
        ).fetchone():
            raise EmailCodeError("username unavailable", HTTPStatus.CONFLICT)
        invite_row = None
        if invite_code:
            invite_row = conn.execute(
                "SELECT * FROM admin_register_tokens WHERE token = ? AND used_by_admin_id IS NULL",
                (invite_code,),
            ).fetchone()
            if not invite_row:
                raise EmailCodeError("invalid or already used invite code", HTTPStatus.BAD_REQUEST)
            if conn.execute("SELECT 1 FROM admin_accounts WHERE username = ? LIMIT 1", (username,)).fetchone():
                raise EmailCodeError("admin username already registered", HTTPStatus.CONFLICT)
            if conn.execute(
                "SELECT 1 FROM admin_accounts WHERE lower(email) = ? LIMIT 1", (email,)
            ).fetchone():
                raise EmailCodeError("admin email already registered", HTTPStatus.CONFLICT)

        existing_user = conn.execute("SELECT * FROM users WHERE username = ? LIMIT 1", (username,)).fetchone()
        if existing_user and existing_user["email_verified_at"]:
            raise EmailCodeError("username already registered", HTTPStatus.CONFLICT)
        if existing_user and not verify_password(password, existing_user["password"]):
            # An unverified legacy row can only be activated by proving knowledge
            # of its original password as well as control of the new email.
            raise EmailCodeError("username already registered", HTTPStatus.CONFLICT)
        email_owner = conn.execute(
            "SELECT id FROM users WHERE lower(email) = ? AND email_verified_at IS NOT NULL LIMIT 1", (email,)
        ).fetchone()
        if email_owner and (not existing_user or int(email_owner["id"]) != int(existing_user["id"])):
            raise EmailCodeError("email already registered", HTTPStatus.CONFLICT)
        consume_verification_code(conn, email, "register", code)
        verified_at = now_iso()
        password_hash = hash_password(password)
        if existing_user:
            user_id = existing_user["id"]
            conn.execute(
                "UPDATE users SET password = ?, email = ?, email_verified_at = ? WHERE id = ?",
                (password_hash, email, verified_at, user_id),
            )
        else:
            cursor = conn.execute(
                "INSERT INTO users (username, password, email, email_verified_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, email, verified_at, verified_at),
            )
            user_id = cursor.lastrowid
        if invite_row:
            admin_cursor = conn.execute(
                "INSERT INTO admin_accounts "
                "(username, password_hash, email, created_at, created_by, is_super, admin_level) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (
                    username,
                    password_hash,
                    email,
                    verified_at,
                    invite_row["created_by"],
                    int(invite_row["admin_level"] or 1),
                ),
            )
            conn.execute(
                "UPDATE admin_register_tokens SET used_by_admin_id = ?, used_at = ? WHERE id = ?",
                (admin_cursor.lastrowid, verified_at, invite_row["id"]),
            )
        award_registration(conn, int(user_id))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except EmailCodeError as exc:
        conn.commit()  # persist failed-attempt counters / code invalidation
        handler.send_json({"error": exc.message}, status=exc.status)
        return
    except sqlite3.IntegrityError:
        conn.rollback()
        handler.send_json({"error": "username or email already registered"}, status=HTTPStatus.CONFLICT)
        return
    except Exception:
        conn.rollback()
        raise
    _start_user_session(handler, row)


def _login_username_password(conn, username, password):
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not verify_password(password, row["password"]):
        return None
    if not row["email_verified_at"]:
        raise EmailCodeError("registration required", HTTPStatus.FORBIDDEN)
    if not (row["password"] or "").startswith("pbkdf2_sha256$"):
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(password), row["id"]))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    return row


def _login_email_password(conn, email, password):
    row = conn.execute(
        "SELECT * FROM users WHERE lower(email) = ? AND email_verified_at IS NOT NULL LIMIT 1", (email,)
    ).fetchone()
    if not row or not verify_password(password, row["password"]):
        return None
    if not (row["password"] or "").startswith("pbkdf2_sha256$"):
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(password), row["id"]))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    return row


def handle_user_login(handler):
    """POST /api/user/login — username/password, email/code, or email/password."""
    body = _read_body(handler)
    if body is None:
        return
    method = (body.get("method") or "username_password").strip().lower()
    conn = get_db()
    row = None

    if method == "username_password":
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        if not username or not password:
            handler.send_json({"error": "credentials required"}, status=HTTPStatus.BAD_REQUEST)
            return
        registration_error = None
        try:
            row = _login_username_password(conn, username, password)
        except EmailCodeError as exc:
            registration_error = exc
        if not row:
            admin = _find_admin_credentials(conn, username, password)
            if admin:
                _start_admin_only_session(
                    handler,
                    admin["username"],
                    admin["is_super"],
                    admin["admin_level"],
                )
                return
        if registration_error:
            handler.send_json({"error": registration_error.message}, status=registration_error.status)
            return
    elif method == "email_password":
        email = normalize_email(body.get("email"))
        password = body.get("password") or ""
        if not EMAIL_RE.fullmatch(email) or not password:
            handler.send_json({"error": "credentials required"}, status=HTTPStatus.BAD_REQUEST)
            return
        row = _login_email_password(conn, email, password)
    elif method == "email_code":
        email = normalize_email(body.get("email"))
        code = (body.get("code") or "").strip()
        if not EMAIL_RE.fullmatch(email) or not code:
            handler.send_json({"error": "credentials required"}, status=HTTPStatus.BAD_REQUEST)
            return
        begin_immediate_with_retry(conn)
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(email) = ? AND email_verified_at IS NOT NULL LIMIT 1", (email,)
            ).fetchone()
            if not row:
                raise EmailCodeError("invalid credentials", HTTPStatus.UNAUTHORIZED)
            consume_verification_code(conn, email, "login", code)
            conn.commit()
        except EmailCodeError as exc:
            conn.commit()
            handler.send_json({"error": exc.message}, status=HTTPStatus.UNAUTHORIZED)
            return
        except Exception:
            conn.rollback()
            raise
    else:
        handler.send_json({"error": "unsupported login method"}, status=HTTPStatus.BAD_REQUEST)
        return

    if not row:
        handler.send_json({"error": "invalid credentials"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _start_user_session(handler, row)


def handle_user_email_bind(handler):
    """POST /api/user/email/bind — bind the first verified email to a legacy account."""
    sess = handler.get_user_session()
    if not sess:
        handler.send_json({"error": "login required"}, status=HTTPStatus.UNAUTHORIZED)
        return
    body = _read_body(handler)
    if body is None:
        return
    email = normalize_email(body.get("email"))
    code = (body.get("code") or "").strip()
    current_password = body.get("currentPassword") or ""
    if not EMAIL_RE.fullmatch(email) or not code or not current_password:
        handler.send_json({"error": "email, code and current password required"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    begin_immediate_with_retry(conn)
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (sess[1].get("user_id"),)).fetchone()
        if not row or not verify_password(current_password, row["password"]):
            raise EmailCodeError("invalid current password", HTTPStatus.UNAUTHORIZED)
        if row["email"] and row["email_verified_at"]:
            raise EmailCodeError("verified email already bound", HTTPStatus.CONFLICT)
        if conn.execute(
            "SELECT 1 FROM users WHERE lower(email) = ? AND email_verified_at IS NOT NULL AND id <> ? LIMIT 1",
            (email, row["id"]),
        ).fetchone():
            raise EmailCodeError("email already registered", HTTPStatus.CONFLICT)
        consume_verification_code(conn, email, "bind", code)
        conn.execute(
            "UPDATE users SET email = ?, email_verified_at = ?, password = ? WHERE id = ?",
            (email, now_iso(), hash_password(current_password), row["id"]),
        )
        conn.commit()
    except EmailCodeError as exc:
        conn.commit()
        handler.send_json({"error": exc.message}, status=exc.status)
        return
    except sqlite3.IntegrityError:
        conn.rollback()
        handler.send_json({"error": "email already registered"}, status=HTTPStatus.CONFLICT)
        return
    except Exception:
        conn.rollback()
        raise
    handler.send_json({"ok": True, "emailMasked": mask_email(email), "hasVerifiedEmail": True})


def _award_daily_for_session(user_data):
    user_id = int(user_data.get("user_id") or 0)
    if not user_id:
        return False
    conn = get_db()
    begin_immediate_with_retry(conn)
    try:
        ledger, awarded = award_daily_activity(conn, user_id)
        conn.commit()
        if awarded and ledger is not None:
            user_data["daily_award_notice"] = int(ledger["delta"] or 0)
        return bool(awarded)
    except PointsError:
        conn.rollback()
        return False
    except Exception:
        conn.rollback()
        raise


def handle_user_logout(handler):
    cookies = handler.parse_cookies()
    token = cookies.get(USER_SESSION_COOKIE)
    if token:
        SESSIONS.pop(token, None)
    # Also clear admin session if present (unified logout)
    admin_token = cookies.get(ADMIN_SESSION_COOKIE)
    if admin_token:
        SESSIONS.pop(admin_token, None)
    blob = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Set-Cookie", f"{USER_SESSION_COOKIE}=deleted; Path=/; Max-Age=0; SameSite=Lax")
    handler.send_header("Set-Cookie", f"{ADMIN_SESSION_COOKIE}=deleted; Path=/; Max-Age=0; SameSite=Lax")
    handler.end_headers()
    handler.wfile.write(blob)


def handle_user_me(handler):
    sess = handler.get_user_session()
    if not sess:
        handler.send_json({"loggedIn": False})
        return
    _, data = sess
    row = _find_user_by_session(data)
    if not row:
        handler.send_json({"loggedIn": False})
        return
    handler.send_json(
        {"loggedIn": True, "username": row["username"], "user_id": row["id"], **_email_payload(row)}
    )


def handle_account_me(handler):
    """GET /api/account/me — unified account info (admin/user/guest)."""
    admin_sess = handler.get_session()
    if admin_sess:
        _, admin = admin_sess
        handler.send_json({
            "loggedIn": True,
            "role": "admin",
            "username": admin.get("username", ""),
            "adminLevel": int(admin.get("admin_level", 1)),
            "isSuper": bool(admin.get("is_super")),
        })
        return
    user_sess = handler.get_user_session()
    if not user_sess:
        handler.send_json({"loggedIn": False, "role": "guest"})
        return
    _, user = user_sess
    username = user.get("username", "")
    if username == ADMIN_USERNAME:
        handler.send_json({"loggedIn": True, "role": "admin", "username": username, "adminLevel": 3, "isSuper": True})
        return
    conn = get_db()
    admin_row = conn.execute(
        "SELECT admin_level, is_super FROM admin_accounts WHERE username = ?", (username,)
    ).fetchone()
    if admin_row:
        handler.send_json({
            "loggedIn": True,
            "role": "admin",
            "username": username,
            "adminLevel": int(admin_row["admin_level"] or 1),
            "isSuper": bool(admin_row["is_super"]),
        })
        return
    row = conn.execute(
        "SELECT id, username, email, email_verified_at FROM users WHERE id = ?", (user.get("user_id"),)
    ).fetchone()
    if not row:
        handler.send_json({"loggedIn": False, "role": "guest"})
        return
    handler.send_json({
        "loggedIn": True,
        "role": "user",
        "username": row["username"],
        "user_id": row["id"],
        **_email_payload(row),
    })
