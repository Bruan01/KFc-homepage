"""
User API handlers — history, download quota, requests, notifications.
"""
from app.db import get_db


def handle_user_history(handler):
    """GET /api/user/history — user download history."""
    sess = handler.require_user_auth()
    if not sess:
        return
    _, user = sess
    user_id = user["user_id"]

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT d.*, p.name AS product_name, p.slug AS product_slug, p.version AS product_version, p.file_name AS product_file
            FROM downloads d
            LEFT JOIN products p ON p.id = d.product_id
            WHERE d.user_id = ?
            ORDER BY d.downloaded_at DESC
            LIMIT 200
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    items = [
        {
            "id": r["id"],
            "product_id": r["product_id"],
            "product_name": r["product_name"] or "",
            "product_slug": r["product_slug"] or "",
            "product_version": r["product_version"] or "",
            "product_file": r["product_file"] or "",
            "downloaded_at": r["downloaded_at"],
        }
        for r in rows
    ]
    handler.send_json({"items": items})


def handle_user_download_quota(handler):
    """GET /api/user/download-quota — per-product download state."""
    sess = handler.require_user_auth()
    if not sess:
        return
    _, user = sess
    user_id = user["user_id"]

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT p.id AS product_id, p.name AS product_name, p.slug AS product_slug, p.version AS product_version,
                   CASE WHEN d0.id IS NULL THEN 0 ELSE 1 END AS used_first_download,
                   CASE WHEN ra.id IS NULL THEN 0 ELSE 1 END AS has_unused_approved_request,
                   CASE WHEN rp.id IS NULL THEN 0 ELSE 1 END AS has_pending_request
            FROM products p
            LEFT JOIN downloads d0
              ON d0.id = (
                SELECT dsub.id
                FROM downloads dsub
                WHERE dsub.product_id = p.id AND dsub.user_id = ?
                ORDER BY dsub.id ASC
                LIMIT 1
              )
            LEFT JOIN download_requests ra
              ON ra.id = (
                SELECT rsub.id
                FROM download_requests rsub
                WHERE rsub.product_id = p.id
                  AND rsub.user_id = ?
                  AND rsub.status = 'approved'
                  AND rsub.consumed_at IS NULL
                ORDER BY rsub.id DESC
                LIMIT 1
              )
            LEFT JOIN download_requests rp
              ON rp.id = (
                SELECT rsub.id
                FROM download_requests rsub
                WHERE rsub.product_id = p.id
                  AND rsub.user_id = ?
                  AND rsub.status = 'pending'
                ORDER BY rsub.id DESC
                LIMIT 1
              )
            WHERE p.status = 'published'
            ORDER BY p.name ASC
            """,
            (user_id, user_id, user_id),
        ).fetchall()
    finally:
        conn.close()

    items = []
    for r in rows:
        used_first = bool(r["used_first_download"])
        has_unused_approved = bool(r["has_unused_approved_request"])
        remaining_downloads = 1 if (not used_first or has_unused_approved) else 0
        items.append(
            {
                "product_id": r["product_id"],
                "product_name": r["product_name"] or "",
                "product_slug": r["product_slug"] or "",
                "product_version": r["product_version"] or "",
                "used_first_download": used_first,
                "has_unused_approved_request": has_unused_approved,
                "has_pending_request": bool(r["has_pending_request"]),
                "remaining_downloads": remaining_downloads,
            }
        )
    handler.send_json({"items": items})


def handle_user_requests(handler):
    """GET /api/user/requests — download requests."""
    sess = handler.require_user_auth()
    if not sess:
        return
    _, user = sess
    user_id = user["user_id"]

    conn = get_db()
    try:
        download_rows = conn.execute(
            """
            SELECT r.*, p.name AS product_name, p.slug AS product_slug
            FROM download_requests r
            LEFT JOIN products p ON p.id = r.product_id
            WHERE r.user_id = ?
            ORDER BY r.id DESC
            LIMIT 200
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    items = [
        {
            "id": r["id"],
            "product_id": r["product_id"],
            "product_name": r["product_name"] or "",
            "product_slug": r["product_slug"] or "",
            "reason": r["reason"] or "",
            "status": r["status"],
            "created_at": r["created_at"],
            "reviewed_at": r["reviewed_at"],
            "review_note": r["review_note"],
            "consumed_at": r["consumed_at"],
        }
        for r in download_rows
    ]
    handler.send_json({"items": items})

def handle_user_notifications(handler):
    """GET /api/user/notifications — product announcements for subscribed users."""
    sess = handler.require_user_auth()
    if not sess:
        return
    _, user = sess
    user_id = user["user_id"]

    conn = get_db()
    try:
        subscribed = conn.execute(
            "SELECT 1 FROM user_subscriptions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not subscribed:
            handler.send_json({"subscribed": False, "items": []})
            return

        rows = conn.execute(
            """
            SELECT id, name, slug, version, announcement, published_at, updated_at
            FROM products
            WHERE status = 'published' AND TRIM(COALESCE(announcement, '')) != ''
            ORDER BY COALESCE(published_at, updated_at) DESC
            LIMIT 20
            """,
        ).fetchall()
    finally:
        conn.close()

    items = [
        {
            "product_id": r["id"],
            "product_name": r["name"],
            "product_slug": r["slug"],
            "version": r["version"],
            "announcement": r["announcement"],
            "published_at": r["published_at"] or r["updated_at"],
        }
        for r in rows
    ]
    handler.send_json({"subscribed": True, "items": items})
