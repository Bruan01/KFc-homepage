"""
Admin settings handlers.
"""
from http import HTTPStatus

from app.db import get_db
from app.utils.upload_limits import (
    get_upload_limit_settings,
    save_upload_limit_settings,
    validate_upload_limit_payload,
)


def handle_admin_upload_settings_get(handler):
    """GET /api/admin/upload-settings"""
    if not handler.require_auth():
        return
    conn = get_db()
    try:
        handler.send_json(get_upload_limit_settings(conn))
    finally:
        conn.close()


def handle_admin_upload_settings_update(handler):
    """POST /api/admin/upload-settings"""
    admin = handler.require_level3_auth()
    if not admin:
        return
    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return

    payload, error_text = validate_upload_limit_payload(body)
    if error_text:
        handler.send_json({"error": error_text}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        save_upload_limit_settings(conn, payload, admin.get("username", ""))
        conn.commit()
        handler.send_json({"ok": True, **get_upload_limit_settings(conn)})
    finally:
        conn.close()
