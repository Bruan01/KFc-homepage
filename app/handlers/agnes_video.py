"""
Agnes Video generation API handlers.
"""
from http import HTTPStatus
from urllib.parse import urlparse

from app.config import AGNES_FREE_VIDEO_LIMIT
from app.db import get_db
from app.utils.helpers import now_iso, extract_video_url


# ── Tasks ──


def handle_agnes_tasks_get(handler):
    """GET /api/agnes/tasks — list current user's video tasks."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    owner = handler.get_current_agnes_owner(auth_ctx)
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, task_id, owner_role, owner_name, model, prompt, status, progress, video_url, seconds, is_public, public_at, last_error, created_at, updated_at
            FROM agnes_video_tasks
            WHERE owner_key = ?
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            (owner["owner_key"],),
        ).fetchall()
    finally:
        conn.close()
    items = [
        {
            "id": r["id"],
            "task_id": r["task_id"],
            "owner_role": r["owner_role"] or "guest",
            "owner_name": r["owner_name"] or "guest",
            "model": r["model"] or "",
            "prompt": r["prompt"] or "",
            "status": r["status"] or "",
            "progress": int(r["progress"] or 0),
            "video_url": r["video_url"] or "",
            "seconds": r["seconds"] or "",
            "is_public": bool(int(r["is_public"] or 0)),
            "public_at": r["public_at"] or None,
            "last_error": r["last_error"] or "",
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]
    handler.send_json({"owner": owner, "items": items})


def handle_agnes_public_videos_get(handler):
    """GET /api/agnes/public-videos — list public completed videos."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    parsed = urlparse(handler.path)
    limit = 80
    query = parsed.query or ""
    for pair in query.split("&"):
        if pair.startswith("limit="):
            raw = (pair.split("=", 1)[1] or "").strip()
            try:
                limit = int(raw)
            except ValueError:
                limit = 80
    limit = max(1, min(200, limit))

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT task_id, owner_role, owner_name, prompt, video_url, seconds, status, progress, public_at, updated_at
            FROM agnes_video_tasks
            WHERE is_public = 1
              AND status = 'completed'
              AND TRIM(COALESCE(video_url, '')) != ''
            ORDER BY COALESCE(public_at, updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    items = [
        {
            "task_id": r["task_id"] or "",
            "owner_role": r["owner_role"] or "",
            "owner_name": r["owner_name"] or "",
            "prompt": r["prompt"] or "",
            "video_url": r["video_url"] or "",
            "seconds": r["seconds"] or "",
            "status": r["status"] or "",
            "progress": int(r["progress"] or 0),
            "public_at": r["public_at"] or None,
            "updated_at": r["updated_at"] or None,
        }
        for r in rows
    ]
    handler.send_json({"items": items})


def handle_agnes_task_public_update(handler, path: str):
    """PUT /api/agnes/tasks/<id>/public — toggle task public visibility."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    owner = handler.get_current_agnes_owner(auth_ctx)
    parts = [p for p in path.split("/") if p]
    if len(parts) != 5 or parts[4] != "public":
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        task_id = parts[3]
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    is_public = 1 if body.get("is_public") else 0
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, owner_key FROM agnes_video_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            handler.send_json({"error": "task not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if row["owner_key"] != owner["owner_key"]:
            handler.send_json({"error": "not your task"}, status=HTTPStatus.FORBIDDEN)
            return
        now = now_iso()
        if is_public:
            conn.execute(
                "UPDATE agnes_video_tasks SET is_public = 1, public_at = COALESCE(public_at, ?), updated_at = ? WHERE task_id = ?",
                (now, now, task_id),
            )
        else:
            conn.execute(
                "UPDATE agnes_video_tasks SET is_public = 0, updated_at = ? WHERE task_id = ?",
                (now, task_id),
            )
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True, "is_public": bool(is_public)})


def handle_agnes_task_delete(handler, path: str):
    """DELETE /api/agnes/tasks/<id> — delete a task."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    owner = handler.get_current_agnes_owner(auth_ctx)
    parts = [p for p in path.split("/") if p]
    if len(parts) != 4:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        task_id = parts[3]
    except ValueError:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, owner_key FROM agnes_video_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            handler.send_json({"error": "task not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if row["owner_key"] != owner["owner_key"]:
            handler.send_json({"error": "not your task"}, status=HTTPStatus.FORBIDDEN)
            return
        conn.execute("DELETE FROM agnes_video_tasks WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM agnes_video_usage_events WHERE task_id = ?", (task_id,))
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True})


# ── Video creation ──


def handle_agnes_video_create(handler):
    """POST /api/agnes/videos — create a new video generation task."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    owner = handler.get_current_agnes_owner(auth_ctx)

    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        handler.send_json({"error": "prompt required"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        api_key_row = handler.pick_agnes_api_key(conn)
        if not api_key_row:
            handler.send_json({"error": "no enabled api key"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        api_key_id = int(api_key_row["id"])
        api_key = str(api_key_row["api_key"]).strip()

        # Deduct quota for non-admin users
        if auth_ctx.get("role") == "user":
            user_id = int(auth_ctx.get("user_id") or 0)
            quota = handler.get_agnes_video_quota_summary(conn, user_id)
            if not quota["can_create_now"]:
                handler.send_json({"error": "quota exhausted"}, status=HTTPStatus.FORBIDDEN)
                return

        model = str(body.get("model") or "agnese-2.0").strip()
        payload = {"model": model, "prompt": prompt}
        status, upstream_resp = _call_agnes_video_upstream(api_key, payload)
        if status is None:
            handler.send_json(
                {"error": "upstream unavailable", "detail": upstream_resp.get("error")},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if status >= 400:
            handler.send_json(
                {"error": "upstream error", "detail": upstream_resp.get("error") or upstream_resp.get("raw", "")},
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        task_id = str(upstream_resp.get("task_id") or upstream_resp.get("data", {}).get("task_id") or "")

        # Deduct quota after successful upstream submission
        if auth_ctx.get("role") == "user":
            conn.execute(
                """
                UPDATE agnes_video_requests
                SET consumed_at = ?, consumed_task_id = ?
                WHERE user_id = ? AND status = 'approved' AND consumed_at IS NULL
                ORDER BY id ASC LIMIT 1
                """,
                (now_iso(), task_id, user_id),
            )
            if conn.total_changes == 0:
                conn.execute(
                    "INSERT INTO agnes_video_usage_events (user_id, task_id, consumed_from, created_at) VALUES (?, ?, 'free', ?)",
                    (user_id, task_id, now_iso()),
                )

        handler.upsert_agnes_task_binding(conn, task_id, api_key_id, owner, {"model": model, "prompt": prompt, "status": "queued"})
        conn.commit()
    finally:
        conn.close()

    handler.send_json({"ok": True, "task_id": task_id})


def handle_agnes_video_get(handler, path: str):
    """GET /api/agnes/videos/<task_id> — check single task status with upstream."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return

    task_id = path.split("/api/agnes/videos/", 1)[1].strip()
    if not task_id:
        handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        return

    conn = get_db()
    try:
        task_row = conn.execute(
            "SELECT * FROM agnes_video_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not task_row:
            handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return

        owner = handler.get_current_agnes_owner(auth_ctx)
        if task_row["owner_key"] != owner["owner_key"]:
            handler.send_json({"error": "not your task"}, status=HTTPStatus.FORBIDDEN)
            return

        # Try upstream refresh
        key_row = handler.get_task_bound_key(conn, task_id)
        api_key = str(key_row["api_key"]).strip() if key_row else ""
        if api_key:
            upstream_status, upstream_data = _call_agnes_video_status(api_key, task_id)
            if upstream_status and upstream_status < 400 and isinstance(upstream_data, dict):
                video_url = extract_video_url(upstream_data)
                new_status = str(upstream_data.get("status") or task_row["status"] or "")
                handler.upsert_agnes_task_binding(conn, task_id, int(task_row["api_key_id"] or 0), owner, {
                    **upstream_data,
                    "status": new_status,
                    "video_url": video_url,
                })
                conn.commit()

        task_row = conn.execute(
            "SELECT * FROM agnes_video_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()

    handler.send_json(
        {
            "task_id": task_row["task_id"],
            "model": task_row["model"] or "",
            "prompt": task_row["prompt"] or "",
            "status": task_row["status"] or "",
            "progress": int(task_row["progress"] or 0),
            "video_url": task_row["video_url"] or "",
            "seconds": task_row["seconds"] or "",
            "is_public": bool(int(task_row["is_public"] or 0)),
            "public_at": task_row["public_at"] or None,
            "last_error": task_row["last_error"] or "",
            "created_at": task_row["created_at"],
            "updated_at": task_row["updated_at"],
        }
    )


# ── Quota & Requests ──


def handle_agnes_quota_get(handler):
    """GET /api/agnes/quota — check video generation quota."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    if auth_ctx.get("role") == "admin":
        handler.send_json(
            {
                "is_admin": True,
                "free_limit": AGNES_FREE_VIDEO_LIMIT,
                "used_count": 0,
                "remaining_free": AGNES_FREE_VIDEO_LIMIT,
                "approved_unused_count": 0,
                "has_pending_request": False,
                "can_create_now": True,
                "rule": "admin-unlimited",
            }
        )
        return
    user_id = int(auth_ctx.get("user_id") or 0)

    conn = get_db()
    try:
        quota = handler.get_agnes_video_quota_summary(conn, user_id)
    finally:
        conn.close()
    handler.send_json(quota)


def handle_agnes_video_request_create(handler):
    """POST /api/agnes/requests — submit a request for more video quota."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    if auth_ctx.get("role") == "admin":
        handler.send_json(
            {"error": "admin-unlimited-no-request-required"},
            status=HTTPStatus.BAD_REQUEST,
        )
        return
    user_id = int(auth_ctx.get("user_id") or 0)
    owner = handler.get_current_agnes_owner(auth_ctx)

    try:
        body = handler.read_json_body()
    except Exception:
        body = {}
    reason = (body.get("reason") or "").strip()[:1000]
    if not reason:
        handler.send_json({"error": "reason required"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        pending = conn.execute(
            "SELECT 1 FROM agnes_video_requests WHERE user_id = ? AND status = 'pending' LIMIT 1",
            (user_id,),
        ).fetchone()
        if pending:
            handler.send_json({"error": "request already pending"}, status=HTTPStatus.CONFLICT)
            return
        conn.execute(
            "INSERT INTO agnes_video_requests (user_id, reason, status, created_at) VALUES (?, ?, 'pending', ?)",
            (user_id, reason, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True})


def handle_agnes_runtime_get(handler):
    """GET /api/agnes/runtime — runtime status info."""
    from app.config import SERVER_RUNTIME
    handler.send_json({
        "chat_token_refreshed_at": SERVER_RUNTIME["chat_token_refreshed_at"],
    })


# ── Upstream helpers ──


def _call_agnes_video_upstream(api_key: str, payload: dict):
    """Call upstream Agnes API to create a video task."""
    from app.services.agnes_api import call_agnes_upstream
    return call_agnes_upstream("POST", "/videos", api_key, payload)


def _call_agnes_video_status(api_key: str, task_id: str):
    """Call upstream Agnes API to check video task status."""
    from app.services.agnes_api import call_agnes_upstream
    return call_agnes_upstream("GET", f"/videos/{task_id}", api_key)
