"""
Admin request review handlers — download request approval, video request approval.
"""
from http import HTTPStatus
from urllib.parse import urlparse

from app.db import get_db
from app.utils.helpers import now_iso


def handle_admin_download_requests_get(handler, path: str):
    """GET /api/admin/download-requests[?status=...]"""
    if not handler.require_auth():
        return

    parsed = urlparse(path)
    view = "pending"
    if "?" in path:
        query = parsed.query
        for pair in query.split("&"):
            if pair.startswith("status="):
                view = pair.split("=", 1)[1] or "pending"
    if view not in {"pending", "approved", "rejected", "all"}:
        view = "pending"

    conn = get_db()
    try:
        sql = """
            SELECT r.*, u.username, p.name as product_name, p.slug as product_slug
            FROM download_requests r
            JOIN users u ON u.id = r.user_id
            JOIN products p ON p.id = r.product_id
        """
        params = ()
        if view != "all":
            sql += " WHERE r.status = ? "
            params = (view,)
        sql += " ORDER BY r.id DESC LIMIT 300"
        rows = conn.execute(sql, params).fetchall()
        items = []
        for r in rows:
            items.append(
                {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "product_id": r["product_id"],
                    "product_name": r["product_name"],
                    "product_slug": r["product_slug"],
                    "reason": r["reason"],
                    "status": r["status"],
                    "review_note": r["review_note"],
                    "created_at": r["created_at"],
                    "reviewed_at": r["reviewed_at"],
                    "reviewed_by": r["reviewed_by"],
                    "consumed_at": r["consumed_at"],
                }
            )
    finally:
        conn.close()

    handler.send_json({"items": items})


def _admin_review_request(handler, path: str, new_status: str):
    """Generic download request approval/rejection."""
    if not handler.require_level2_auth():
        return
    parts = [p for p in path.split("/") if p]
    if len(parts) != 5:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        req_id = int(parts[3])
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    note = (body.get("note") or "").strip()[:1000]
    admin = handler.get_session()[1]["username"]

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM download_requests WHERE id = ?", (req_id,)).fetchone()
        if not row:
            handler.send_json({"error": "request not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if row["status"] != "pending":
            handler.send_json({"error": "request already reviewed"}, status=HTTPStatus.CONFLICT)
            return
        conn.execute(
            """
            UPDATE download_requests
            SET status = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (new_status, note, now_iso(), admin, req_id),
        )
        conn.commit()
    finally:
        conn.close()

    handler.send_json({"ok": True, "status": new_status})


def handle_admin_download_request_approve(handler, path: str):
    return _admin_review_request(handler, path, "approved")


def handle_admin_download_request_reject(handler, path: str):
    return _admin_review_request(handler, path, "rejected")


def handle_admin_agnes_video_requests_get(handler, path: str):
    """GET /api/admin/agnes-video-requests[?status=...]"""
    if not handler.require_level2_auth():
        return
    parsed = urlparse(path)
    view = "pending"
    query = parsed.query or ""
    for pair in query.split("&"):
        if pair.startswith("status="):
            view = pair.split("=", 1)[1] or "pending"
    if view not in {"pending", "approved", "rejected", "all"}:
        view = "pending"

    conn = get_db()
    try:
        sql = """
            SELECT r.*, u.username
            FROM agnes_video_requests r
            JOIN users u ON u.id = r.user_id
        """
        params = ()
        if view != "all":
            sql += " WHERE r.status = ? "
            params = (view,)
        sql += " ORDER BY r.id DESC LIMIT 300"
        rows = conn.execute(sql, params).fetchall()
        items = []
        for r in rows:
            items.append(
                {
                    "id": int(r["id"]),
                    "user_id": int(r["user_id"]),
                    "username": r["username"] or "",
                    "reason": r["reason"] or "",
                    "status": r["status"] or "",
                    "review_note": r["review_note"] or "",
                    "created_at": r["created_at"] or None,
                    "reviewed_at": r["reviewed_at"] or None,
                    "reviewed_by": r["reviewed_by"] or "",
                    "consumed_at": r["consumed_at"] or None,
                    "consumed_task_id": r["consumed_task_id"] or "",
                }
            )
    finally:
        conn.close()
    handler.send_json({"items": items})


def _admin_review_agnes_video_request(handler, path: str, new_status: str):
    """Generic Agnes video request approval/rejection."""
    if not handler.require_level2_auth():
        return
    parts = [p for p in path.split("/") if p]
    if len(parts) != 5:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        req_id = int(parts[3])
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    note = str(body.get("note") or "").strip()[:1000]
    admin = handler.get_session()[1]["username"]
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM agnes_video_requests WHERE id = ?", (req_id,)).fetchone()
        if not row:
            handler.send_json({"error": "request not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if row["status"] != "pending":
            handler.send_json({"error": "request already reviewed"}, status=HTTPStatus.CONFLICT)
            return
        conn.execute(
            """
            UPDATE agnes_video_requests
            SET status = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (new_status, note, now_iso(), admin, req_id),
        )
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True, "status": new_status})


def handle_admin_agnes_video_request_approve(handler, path: str):
    return _admin_review_agnes_video_request(handler, path, "approved")


def handle_admin_agnes_video_request_reject(handler, path: str):
    return _admin_review_agnes_video_request(handler, path, "rejected")
