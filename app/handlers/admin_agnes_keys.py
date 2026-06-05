"""
Admin Agnes API key management handlers.
"""
import secrets
from http import HTTPStatus

from app.db import get_db
from app.utils.helpers import mask_api_key, now_iso


def handle_admin_agnes_keys_get(handler):
    """GET /api/admin/agnes-keys"""
    if not handler.require_auth():
        return
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM agnes_api_keys ORDER BY id ASC"
        ).fetchall()
        items = [
            {
                "id": r["id"],
                "label": r["label"] or "",
                "api_key": mask_api_key(r["api_key"] or ""),
                "enabled": bool(int(r["enabled"] or 0)),
                "created_by": r["created_by"] or "",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "last_used_at": r["last_used_at"] or None,
                "use_count": int(r["use_count"] or 0),
            }
            for r in rows
        ]
    finally:
        conn.close()
    handler.send_json({"items": items})


def handle_admin_agnes_keys_create(handler):
    """POST /api/admin/agnes-keys"""
    sess = handler.require_level2_auth()
    if not sess:
        return
    _, admin = sess
    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return
    label = (body.get("label") or "").strip()[:120]
    api_key = (body.get("api_key") or "").strip()
    if not api_key:
        handler.send_json({"error": "api_key required"}, status=HTTPStatus.BAD_REQUEST)
        return
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO agnes_api_keys (label, api_key, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (label, api_key, admin["username"], now_iso(), now_iso()),
        )
        conn.commit()
    except Exception:
        handler.send_json({"error": "key may already exist"}, status=HTTPStatus.CONFLICT)
        return
    finally:
        conn.close()
    handler.send_json({"ok": True})


def handle_admin_agnes_keys_update(handler, path: str):
    """PUT /api/admin/agnes-keys/<id>"""
    sess = handler.require_level2_auth()
    if not sess:
        return
    _, admin = sess
    parts = [p for p in path.split("/") if p]
    if len(parts) != 4:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        key_id = int(parts[3])
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM agnes_api_keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        label = str(body.get("label") if "label" in body else row["label"] or "").strip()[:120]
        enabled = body.get("enabled") if "enabled" in body else bool(row.get("enabled"))
        conn.execute(
            "UPDATE agnes_api_keys SET label = ?, enabled = ?, updated_at = ? WHERE id = ?",
            (label, 1 if enabled else 0, now_iso(), key_id),
        )
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True})


def handle_admin_agnes_keys_delete(handler, path: str):
    """DELETE /api/admin/agnes-keys/<id>"""
    sess = handler.require_level2_auth()
    if not sess:
        return
    parts = [p for p in path.split("/") if p]
    if len(parts) != 4:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        key_id = int(parts[3])
    except ValueError:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        conn.execute("DELETE FROM agnes_api_keys WHERE id = ?", (key_id,))
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True})
