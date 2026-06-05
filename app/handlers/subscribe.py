"""
Subscribe handler.
"""
from http import HTTPStatus

from app.db import get_db
from app.utils.helpers import now_iso


def handle_subscribe(handler):
    """POST /api/subscribe — subscribe logged-in users to product announcements."""
    user_sess = handler.get_user_session()
    if not user_sess:
        admin_sess = handler.get_session()
        if admin_sess:
            handler.send_json({"ok": True, "message": "admin session, no subscribe needed"})
            return
        handler.send_json({"error": "user login required"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, user = user_sess
    user_id = user["user_id"]
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO user_subscriptions (user_id, created_at) VALUES (?, ?)",
            (user_id, now_iso()),
        )
        conn.commit()
    except Exception:
        return handler.send_json({"ok": True, "message": "already subscribed"})
    finally:
        conn.close()

    handler.send_json({"ok": True})
