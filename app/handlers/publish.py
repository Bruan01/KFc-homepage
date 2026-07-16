"""
Publish request workflow handlers — create, vote, list.
"""
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus

from app.config import ADMIN_USERNAME, BASE_DIR, PUBLISH_REVIEW_TIMEOUT_MINUTES
from app.db import get_db, begin_immediate_with_retry
from app.utils.helpers import now_iso


def _delete_product_graph(conn: sqlite3.Connection, product_id: int) -> None:
    """Delete a product and every row that still holds an FK to it."""
    request_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM publish_requests WHERE product_id = ?", (product_id,)).fetchall()
    ]
    if request_ids:
        placeholders = ",".join("?" for _ in request_ids)
        conn.execute(f"DELETE FROM publish_request_votes WHERE request_id IN ({placeholders})", request_ids)

    conn.execute("DELETE FROM publish_requests WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM download_requests WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM downloads WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM product_versions WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM admin_upload_events WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM product_delete_requests WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


def handle_publish_request_create(handler):
    """POST /api/admin/publish-requests — create a publish request or direct-publish for lv3+."""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = sess
    requester = admin["username"]
    requester_level = max(1, min(3, int(admin.get("admin_level", 1))))

    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return

    product_id = body.get("product_id")
    if product_id is None:
        handler.send_json({"error": "product_id required"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        handler.send_json({"error": "invalid product_id"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            handler.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if row["status"] == "published":
            handler.send_json({"error": "product already published"}, status=HTTPStatus.CONFLICT)
            return
        if not row["file_path"]:
            handler.send_json({"error": "product has no package file"}, status=HTTPStatus.BAD_REQUEST)
            return

        if requester_level >= 3:
            now = now_iso()
            conn.execute(
                "UPDATE products SET status = 'published', published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?",
                (now, now, product_id),
            )
            conn.commit()
            new_row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            out = _product_row_dict(new_row)
            out["direct_published"] = True
            handler.send_json(out)
            return

        pending = conn.execute(
            "SELECT id FROM publish_requests WHERE product_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        if pending:
            handler.send_json({"error": "publish request already pending"}, status=HTTPStatus.CONFLICT)
            return

        scope, min_level = _publish_reviewer_scope(requester_level)
        reviewers = _list_reviewer_usernames(min_level=min_level, exclude_username=requester)
        pool_count = len(reviewers)
        if pool_count <= 0:
            handler.send_json({"error": "no eligible reviewers found"}, status=HTTPStatus.CONFLICT)
            return
        pool_weight = _compute_reviewer_pool_weight(reviewers, scope)
        threshold_weight = (pool_weight // 2) + 1
        expires_at = datetime.fromtimestamp(time.time() + PUBLISH_REVIEW_TIMEOUT_MINUTES * 60, timezone.utc).isoformat()

        cur = conn.execute(
            """
            INSERT INTO publish_requests (
                product_id, requested_by, requester_level, reviewer_scope,
                reviewer_pool_count, reviewer_pool_weight, approve_threshold_weight, status, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (product_id, requester, requester_level, scope, pool_count, pool_weight, threshold_weight, now_iso(), expires_at),
        )
        conn.commit()
    finally:
        conn.close()

    handler.send_json({"ok": True, "request_id": cur.lastrowid})


def handle_publish_request_vote(handler, path: str):
    """POST /api/admin/publish-requests/<id>/vote — cast a vote."""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = sess
    me = admin["username"]
    my_level = max(1, min(3, int(admin.get("admin_level", 1))))

    parts = [p for p in path.split("/") if p]
    if len(parts) != 5 or parts[4] != "vote":
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        req_id = int(parts[3])
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    vote = (body.get("vote") or "").strip()
    note = (body.get("note") or "").strip()[:1000]
    if vote not in {"approve", "reject"}:
        handler.send_json({"error": "vote must be 'approve' or 'reject'"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        begin_immediate_with_retry(conn)
        req = conn.execute("SELECT * FROM publish_requests WHERE id = ?", (req_id,)).fetchone()
        if not req:
            conn.rollback()
            handler.send_json({"error": "request not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if req["status"] != "pending":
            conn.rollback()
            handler.send_json({"error": "request already decided"}, status=HTTPStatus.CONFLICT)
            return
        if req["requested_by"] == me:
            conn.rollback()
            handler.send_json({"error": "cannot vote on own request"}, status=HTTPStatus.FORBIDDEN)
            return
        required_level = 2 if req["reviewer_scope"] == "lv2plus" else 3
        if my_level < required_level:
            conn.rollback()
            handler.send_json({"error": f"lv{required_level}+ required to vote"}, status=HTTPStatus.FORBIDDEN)
            return

        existing = conn.execute(
            "SELECT id FROM publish_request_votes WHERE request_id = ? AND reviewer_username = ?",
            (req_id, me),
        ).fetchone()
        if existing:
            conn.rollback()
            handler.send_json({"error": "already voted"}, status=HTTPStatus.CONFLICT)
            return

        conn.execute(
            "INSERT INTO publish_request_votes (request_id, reviewer_username, reviewer_level, vote, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (req_id, me, my_level, vote, note, now_iso()),
        )

        agree_weight = conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
            FROM publish_request_votes WHERE request_id = ? AND vote = 'approve'
            """,
            (req_id,),
        ).fetchone()[0]
        reject_weight = conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
            FROM publish_request_votes WHERE request_id = ? AND vote = 'reject'
            """,
            (req_id,),
        ).fetchone()[0]
        threshold_weight = int(req["approve_threshold_weight"] or 0)
        pool_weight = int(req["reviewer_pool_weight"] or 0)
        max_possible_approve_weight = pool_weight - reject_weight

        if agree_weight >= threshold_weight:
            now = now_iso()
            conn.execute(
                "UPDATE publish_requests SET status = 'approved', decided_at = ?, decided_note = ? WHERE id = ?",
                (now, note, req_id),
            )
            conn.execute(
                "UPDATE products SET status = 'published', published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?",
                (now, now, req["product_id"]),
            )
            final_status = "approved"
        elif max_possible_approve_weight < threshold_weight:
            now = now_iso()
            conn.execute(
                "UPDATE publish_requests SET status = 'rejected', decided_at = ?, decided_note = ? WHERE id = ?",
                (now, note, req_id),
            )
            final_status = "rejected"
        else:
            final_status = "pending"

        conn.commit()
    finally:
        conn.close()

    handler.send_json(
        {
            "ok": True,
            "status": final_status,
            "agree_weight": agree_weight,
            "reject_weight": reject_weight,
            "threshold_weight": threshold_weight,
        }
    )


def handle_publish_requests_get(handler):
    """GET /api/admin/publish-requests — list publish requests."""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = sess
    me = admin["username"]
    my_level = max(1, min(3, int(admin.get("admin_level", 1))))

    conn = get_db()
    try:
        if my_level <= 1 and not bool(admin.get("is_super")):
            rows = conn.execute(
                """
                SELECT r.*, p.name AS product_name, p.slug AS product_slug
                FROM publish_requests r
                JOIN products p ON p.id = r.product_id
                WHERE r.requested_by = ?
                ORDER BY r.id DESC
                LIMIT 300
                """,
                (me,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT r.*, p.name AS product_name, p.slug AS product_slug
                FROM publish_requests r
                JOIN products p ON p.id = r.product_id
                ORDER BY r.id DESC
                LIMIT 300
                """
            ).fetchall()

        items = []
        for r in rows:
            r = _finalize_publish_request_if_due(conn, r)
            agree_weight = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
                FROM publish_request_votes WHERE request_id = ? AND vote = 'approve'
                """,
                (r["id"],),
            ).fetchone()[0]
            reject_weight = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
                FROM publish_request_votes WHERE request_id = ? AND vote = 'reject'
                """,
                (r["id"],),
            ).fetchone()[0]
            my_vote = conn.execute(
                "SELECT vote FROM publish_request_votes WHERE request_id = ? AND reviewer_username = ?",
                (r["id"], me),
            ).fetchone()
            required_level = 2 if r["reviewer_scope"] == "lv2plus" else 3
            expired = False
            if r["expires_at"]:
                try:
                    expired = datetime.fromisoformat(r["expires_at"]).timestamp() <= time.time()
                except ValueError:
                    expired = False
            can_vote = (
                r["status"] == "pending"
                and r["requested_by"] != me
                and my_level >= required_level
                and my_vote is None
                and not expired
            )
            items.append(
                {
                    "id": r["id"],
                    "product_id": r["product_id"],
                    "product_name": r["product_name"],
                    "product_slug": r["product_slug"],
                    "requested_by": r["requested_by"],
                    "requester_level": r["requester_level"],
                    "reviewer_scope": r["reviewer_scope"],
                    "reviewer_pool_count": r["reviewer_pool_count"],
                    "reviewer_pool_weight": int(r["reviewer_pool_weight"] or 0),
                    "approve_threshold_weight": int(r["approve_threshold_weight"] or 0),
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "expires_at": r["expires_at"],
                    "decided_at": r["decided_at"],
                    "agree_weight": agree_weight,
                    "reject_weight": reject_weight,
                    "my_vote": my_vote["vote"] if my_vote else None,
                    "expired": expired,
                    "can_vote": can_vote,
                }
            )
        conn.commit()
    finally:
        conn.close()

    handler.send_json({"items": items})


def handle_admin_inbox_get(handler):
    """GET /api/admin/inbox — aggregated pending items for the current admin."""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = sess
    me = admin["username"]
    my_level = max(1, min(3, int(admin.get("admin_level", 1))))

    conn = get_db()
    try:
        download_items = []
        video_request_items = []
        if my_level >= 2:
            drows = conn.execute(
                """
                SELECT r.*, u.username, p.name as product_name, p.slug as product_slug
                FROM download_requests r
                JOIN users u ON u.id = r.user_id
                JOIN products p ON p.id = r.product_id
                WHERE r.status = 'pending'
                ORDER BY r.id DESC
                LIMIT 200
                """
            ).fetchall()
            for r in drows:
                download_items.append(
                    {
                        "type": "download_request",
                        "id": r["id"],
                        "username": r["username"],
                        "product_name": r["product_name"],
                        "product_slug": r["product_slug"],
                        "reason": r["reason"],
                        "created_at": r["created_at"],
                    }
                )
            vrows = conn.execute(
                """
                SELECT r.*, u.username
                FROM agnes_video_requests r
                JOIN users u ON u.id = r.user_id
                WHERE r.status = 'pending'
                ORDER BY r.id DESC
                LIMIT 200
                """
            ).fetchall()
            for r in vrows:
                video_request_items.append(
                    {
                        "type": "agnes_video_request",
                        "id": int(r["id"]),
                        "username": r["username"] or "",
                        "reason": r["reason"] or "",
                        "created_at": r["created_at"] or None,
                    }
                )

        publish_items = []
        prows = conn.execute(
            """
            SELECT r.*, p.name AS product_name, p.slug AS product_slug
            FROM publish_requests r
            JOIN products p ON p.id = r.product_id
            WHERE r.status = 'pending'
            ORDER BY r.id DESC
            LIMIT 300
            """
        ).fetchall()
        for r in prows:
            r = _finalize_publish_request_if_due(conn, r)
            if r["status"] != "pending":
                continue
            my_vote = conn.execute(
                "SELECT vote FROM publish_request_votes WHERE request_id = ? AND reviewer_username = ?",
                (r["id"], me),
            ).fetchone()
            required_level = 2 if r["reviewer_scope"] == "lv2plus" else 3
            can_vote = (
                r["requested_by"] != me
                and my_level >= required_level
                and my_vote is None
            )
            if can_vote:
                agree_weight = conn.execute(
                    """
                    SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
                    FROM publish_request_votes WHERE request_id = ? AND vote = 'approve'
                    """,
                    (r["id"],),
                ).fetchone()[0]
                publish_items.append(
                    {
                        "type": "publish_request",
                        "id": r["id"],
                        "product_name": r["product_name"],
                        "product_slug": r["product_slug"],
                        "requested_by": r["requested_by"],
                        "reviewer_scope": r["reviewer_scope"],
                        "agree_weight": agree_weight,
                        "approve_threshold_weight": int(r["approve_threshold_weight"] or 0),
                        "expires_at": r["expires_at"],
                        "created_at": r["created_at"],
                    }
                )

        delete_items = []
        del_rows = conn.execute(
            """
            SELECT * FROM product_delete_requests
            WHERE status = 'pending' AND owner_username = ?
            ORDER BY id DESC
            LIMIT 200
            """,
            (me,),
        ).fetchall()
        for r in del_rows:
            delete_items.append(
                {
                    "type": "delete_request",
                    "id": r["id"],
                    "product_id": r["product_id"],
                    "product_name": r["product_name"],
                    "product_slug": r["product_slug"],
                    "requested_by": r["requested_by"],
                    "requester_level": r["requester_level"],
                    "reason": r["reason"],
                    "created_at": r["created_at"],
                }
            )
    finally:
        conn.close()

    handler.send_json(
        {
            "download_requests": download_items,
            "agnes_video_requests": video_request_items,
            "publish_requests": publish_items,
            "delete_requests": delete_items,
            "unread_count": len(download_items) + len(video_request_items) + len(publish_items) + len(delete_items),
        }
    )


def handle_delete_request_approve(handler, path: str):
    return _review_delete_request(handler, path, "approve")


def handle_delete_request_reject(handler, path: str):
    return _review_delete_request(handler, path, "reject")


def _review_delete_request(handler, path: str, decision: str):
    """Approve or reject a product delete request."""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = sess
    reviewer = admin["username"]

    parts = [p for p in path.split("/") if p]
    if len(parts) != 5:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        req_id = int(parts[3])
        body = handler.read_json_body() if handler.headers.get("Content-Length") else {}
    except Exception:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    note = (body.get("note") or "").strip()[:1000]

    conn = get_db()
    file_path = ""
    try:
        begin_immediate_with_retry(conn)
        req = conn.execute("SELECT * FROM product_delete_requests WHERE id = ?", (req_id,)).fetchone()
        if not req:
            conn.rollback()
            handler.send_json({"error": "request not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if req["status"] != "pending":
            conn.rollback()
            handler.send_json({"error": "request already reviewed"}, status=HTTPStatus.CONFLICT)
            return
        if req["owner_username"] != reviewer:
            conn.rollback()
            handler.send_json({"error": "only owner can review"}, status=HTTPStatus.FORBIDDEN)
            return

        now = now_iso()
        if decision == "approve":
            row = conn.execute("SELECT * FROM products WHERE id = ?", (req["product_id"],)).fetchone()
            if row:
                file_path = row["file_path"] or ""
                _delete_product_graph(conn, req["product_id"])
            else:
                conn.execute("DELETE FROM product_delete_requests WHERE product_id = ?", (req["product_id"],))
        else:
            conn.execute(
                """
                UPDATE product_delete_requests
                SET status = 'rejected', decided_at = ?, decided_by = ?, decision_note = ?
                WHERE id = ?
                """,
                (now, reviewer, note, req_id),
            )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        handler.send_json({"error": "product delete blocked by related records"}, status=HTTPStatus.CONFLICT)
        return
    finally:
        conn.close()

    if file_path:
        target = (BASE_DIR / file_path).resolve()
        if target.exists() and target.is_file():
            try:
                target.unlink()
            except OSError:
                pass

    handler.send_json({"ok": True, "status": "approved" if decision == "approve" else "rejected"})


# ── Helper functions (publish workflow) ──


def _publish_reviewer_scope(requester_level: int):
    """Determine the reviewer scope and minimum level based on requester level."""
    if requester_level <= 1:
        return "lv2plus", 2
    return "lv3plus", 3


def _list_reviewer_usernames(min_level: int = 2, exclude_username: str = ""):
    """List admin usernames who can review (min_level+), optionally excluding one."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT username FROM admin_accounts WHERE admin_level >= ? ORDER BY id ASC",
            (min_level,),
        ).fetchall()
    finally:
        conn.close()
    usernames = [r["username"] for r in rows]
    if exclude_username and exclude_username in usernames:
        usernames.remove(exclude_username)
    return usernames


def _compute_reviewer_pool_weight(reviewers, scope):
    """Compute total pool weight: lv3 admins count 2, lv2 count 1."""
    if not reviewers:
        return 0
    conn = get_db()
    try:
        weight = 0
        for username in reviewers:
            row = conn.execute(
                "SELECT admin_level FROM admin_accounts WHERE username = ?",
                (username,),
            ).fetchone()
            if row:
                weight += 2 if int(row["admin_level"]) >= 3 else 1
    finally:
        conn.close()
    return weight


def _finalize_publish_request_if_due(conn, req):
    """Auto-finalize a publish request that has expired."""
    if req["status"] != "pending":
        return req
    if not req["expires_at"]:
        return req
    try:
        expires_ts = datetime.fromisoformat(req["expires_at"]).timestamp()
    except ValueError:
        return req
    if expires_ts > time.time():
        return req

    agree_weight = conn.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN reviewer_level >= 3 THEN 2 ELSE 1 END), 0)
        FROM publish_request_votes WHERE request_id = ? AND vote = 'approve'
        """,
        (req["id"],),
    ).fetchone()[0]
    total_votes = conn.execute(
        "SELECT COUNT(*) FROM publish_request_votes WHERE request_id = ?",
        (req["id"],),
    ).fetchone()[0]

    threshold_weight = int(req["approve_threshold_weight"] or 0)
    now = now_iso()
    if total_votes == 0:
        conn.execute(
            "UPDATE publish_requests SET status = 'rejected', decided_at = ?, decided_note = ? WHERE id = ?",
            (now, "timeout: no votes", req["id"]),
        )
    elif agree_weight >= threshold_weight:
        conn.execute(
            "UPDATE publish_requests SET status = 'approved', decided_at = ?, decided_note = ? WHERE id = ?",
            (now, "timeout: approved by weighted majority", req["id"]),
        )
        conn.execute(
            "UPDATE products SET status = 'published', published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?",
            (now, now, req["product_id"]),
        )
    else:
        conn.execute(
            "UPDATE publish_requests SET status = 'rejected', decided_at = ?, decided_note = ? WHERE id = ?",
            (now, "timeout: weighted majority not reached", req["id"]),
        )

    return conn.execute("SELECT * FROM publish_requests WHERE id = ?", (req["id"],)).fetchone()
