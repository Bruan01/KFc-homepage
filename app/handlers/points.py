"""K-points user wallet, download redemption and admin management handlers."""
import secrets
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from app.db import begin_immediate_with_retry, get_db
from app.services.points import (
    PointsError,
    account_payload,
    apply_ledger,
    award_daily_activity,
    get_rules,
    ledger_payload,
    redeem_download,
    save_rules,
)
from app.utils.helpers import now_iso


def _user(handler):
    sess = handler.require_user_auth()
    if not sess:
        return None
    return sess[1]


def handle_points_me(handler):
    user = _user(handler)
    if not user:
        return
    conn = get_db()
    begin_immediate_with_retry(conn)
    try:
        daily, awarded = award_daily_activity(conn, int(user["user_id"]))
        payload = account_payload(conn, int(user["user_id"]))
        conn.commit()
    except PointsError as exc:
        conn.rollback()
        handler.send_json({"error": exc.message}, status=exc.status)
        return
    except Exception:
        conn.rollback()
        raise
    pending_notice = int(user.pop("daily_award_notice", 0) or 0)
    payload["dailyAwarded"] = bool(awarded or pending_notice)
    payload["dailyDelta"] = int(daily["delta"]) if daily is not None and awarded else pending_notice
    handler.send_json(payload)


def handle_points_rules(handler):
    conn = get_db()
    rules = get_rules(conn)
    handler.send_json({"item": rules})


def handle_points_ledger(handler, raw_path: str):
    user = _user(handler)
    if not user:
        return
    query = parse_qs(urlparse(raw_path).query)
    try:
        page = max(1, int(query.get("page", ["1"])[0]))
        page_size = max(1, min(100, int(query.get("pageSize", ["30"])[0])))
    except ValueError:
        page, page_size = 1, 30
    conn = get_db()
    total = int(conn.execute("SELECT COUNT(*) FROM point_ledger WHERE user_id = ?", (user["user_id"],)).fetchone()[0])
    rows = conn.execute(
        "SELECT * FROM point_ledger WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
        (user["user_id"], page_size, (page - 1) * page_size),
    ).fetchall()
    handler.send_json({"items": [ledger_payload(row) for row in rows], "total": total, "page": page, "pageSize": page_size})


def handle_points_entitlements(handler):
    user = _user(handler)
    if not user:
        return
    conn = get_db()
    rows = conn.execute(
        "SELECT e.*, p.name product_name, p.slug product_slug FROM download_entitlements e "
        "JOIN products p ON p.id = e.product_id WHERE e.user_id = ? ORDER BY e.id DESC LIMIT 100",
        (user["user_id"],),
    ).fetchall()
    handler.send_json({"items": [
        {
            "id": row["id"], "productId": row["product_id"], "productName": row["product_name"],
            "productSlug": row["product_slug"], "source": row["source"], "cost": int(row["cost"] or 0),
            "remainingCount": int(row["remaining_count"] or 0), "createdAt": row["created_at"],
            "expiresAt": row["expires_at"], "consumedAt": row["consumed_at"],
        } for row in rows
    ]})


def handle_points_redeem_download(handler):
    user = _user(handler)
    if not user:
        return
    try:
        body = handler.read_json_body()
        product_id = int(body.get("productId"))
    except (Exception, TypeError, ValueError):
        handler.send_json({"error": "productId and JSON body required"}, status=HTTPStatus.BAD_REQUEST)
        return
    idem = str(body.get("idempotencyKey") or "").strip()
    conn = get_db()
    begin_immediate_with_retry(conn)
    try:
        entitlement, account, created = redeem_download(
            conn, user_id=int(user["user_id"]), product_id=product_id, idempotency_key=idem
        )
        conn.commit()
    except PointsError as exc:
        conn.rollback()
        handler.send_json({"error": exc.message}, status=exc.status)
        return
    except Exception:
        conn.rollback()
        raise
    handler.send_json({
        "ok": True,
        "created": created,
        "entitlementId": entitlement["id"],
        "productId": entitlement["product_id"],
        "cost": int(entitlement["cost"] or 0),
        "expiresAt": entitlement["expires_at"],
        "balance": account["balance"],
    }, status=HTTPStatus.CREATED if created else HTTPStatus.OK)


def handle_admin_points_settings_get(handler):
    if not handler.require_level3_auth():
        return
    conn = get_db()
    handler.send_json({"item": get_rules(conn)})


def handle_admin_points_settings_update(handler):
    admin = handler.require_level3_auth()
    if not admin:
        return
    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return
    conn = get_db()
    begin_immediate_with_retry(conn)
    try:
        rules = save_rules(conn, body, admin["username"])
        conn.commit()
    except PointsError as exc:
        conn.rollback()
        handler.send_json({"error": exc.message}, status=exc.status)
        return
    handler.send_json({"ok": True, "item": rules})


def handle_admin_points_accounts(handler, raw_path: str):
    if not handler.require_auth():
        return
    query = parse_qs(urlparse(raw_path).query)
    search = str(query.get("search", [""])[0]).strip()
    conn = get_db()
    params = []
    where = ""
    if search:
        where = "WHERE u.username LIKE ? OR u.email LIKE ?"
        params.extend([f"%{search}%", f"%{search}%"])
    rows = conn.execute(
        "SELECT u.id user_id, u.username, u.email, a.balance, a.total_earned, a.total_spent, "
        "a.contribution_score, a.reputation_level, a.status, a.last_active_date "
        "FROM users u LEFT JOIN point_accounts a ON a.user_id = u.id "
        f"{where} ORDER BY COALESCE(a.contribution_score, 0) DESC, u.id DESC LIMIT 200",
        params,
    ).fetchall()
    handler.send_json({"items": [dict(row) for row in rows]})


def handle_admin_points_adjust(handler):
    admin = handler.require_level3_auth()
    if not admin:
        return
    try:
        body = handler.read_json_body()
        user_id = int(body.get("userId"))
        points_delta = int(body.get("pointsDelta", 0))
        contribution_delta = int(body.get("contributionDelta", 0))
    except (Exception, TypeError, ValueError):
        handler.send_json({"error": "valid adjustment body required"}, status=HTTPStatus.BAD_REQUEST)
        return
    reason = str(body.get("reason") or "").strip()
    if not reason or (points_delta == 0 and contribution_delta == 0):
        handler.send_json({"error": "reason and non-zero adjustment required"}, status=HTTPStatus.BAD_REQUEST)
        return
    conn = get_db()
    begin_immediate_with_retry(conn)
    try:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            raise PointsError("user not found", 404)
        key = f"admin_adjustment:{admin['username']}:{secrets.token_hex(16)}"
        ledger, _ = apply_ledger(
            conn, user_id=user_id, event_type="admin_adjustment", points_delta=points_delta,
            contribution_delta=contribution_delta, idempotency_key=key, description=reason,
            reference_type="admin", reference_id=admin["username"], created_by=admin["username"],
        )
        account = account_payload(conn, user_id)
        conn.commit()
    except PointsError as exc:
        conn.rollback()
        handler.send_json({"error": exc.message}, status=exc.status)
        return
    except Exception:
        conn.rollback()
        raise
    handler.send_json({"ok": True, "ledger": ledger_payload(ledger), "account": account})


def _set_account_status(handler, status: str):
    admin = handler.require_level3_auth()
    if not admin:
        return
    try:
        user_id = int(handler.read_json_body().get("userId"))
    except (Exception, TypeError, ValueError):
        handler.send_json({"error": "userId required"}, status=HTTPStatus.BAD_REQUEST)
        return
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO point_accounts (user_id, updated_at) VALUES (?, ?)", (user_id, now_iso()))
    conn.execute("UPDATE point_accounts SET status = ?, updated_at = ? WHERE user_id = ?", (status, now_iso(), user_id))
    conn.commit()
    handler.send_json({"ok": True, "userId": user_id, "status": status})


def handle_admin_points_freeze(handler):
    _set_account_status(handler, "frozen")


def handle_admin_points_unfreeze(handler):
    _set_account_status(handler, "active")
