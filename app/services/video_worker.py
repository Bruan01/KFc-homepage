"""
Video task refresh worker — polls upstream for task status updates.
"""
import time
from http import HTTPStatus

from app.config import AGNES_TASK_REFRESH_INTERVAL_SECONDS
from app.db import get_db, begin_immediate_with_retry
from app.services.agnes_api import call_agnes_upstream, is_task_not_exist
from app.utils.helpers import extract_video_url, now_iso


def refresh_agnes_tasks_once(limit: int = 100) -> int:
    """Refresh status of in-progress video tasks from upstream. Returns count of updates."""
    read_conn = get_db()
    try:
        rows = read_conn.execute(
            """
            SELECT t.id, t.task_id, t.api_key_id, t.status, t.model, t.prompt, t.video_url, k.api_key
            FROM agnes_video_tasks t
            LEFT JOIN agnes_api_keys k ON k.id = t.api_key_id
            WHERE t.status IN ('', 'queued', 'in_progress')
               OR (t.status = 'completed' AND (t.video_url IS NULL OR t.video_url = ''))
            ORDER BY t.updated_at ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        if not rows:
            return 0

        enabled_keys = read_conn.execute(
            "SELECT id, api_key FROM agnes_api_keys WHERE enabled = 1 ORDER BY id ASC"
        ).fetchall()
    finally:
        read_conn.close()

    updates = []
    now = now_iso()
    for row in rows:
        task_id = str(row["task_id"] or "").strip()
        if not task_id:
            continue

        status = None
        payload = None
        chosen_key_id = int(row["api_key_id"] or 0)

        # First try the bound key
        if row["api_key"]:
            status, payload = call_agnes_upstream("GET", f"/videos/{task_id}", row["api_key"])

        # Fallback scan when bound key fails
        need_fallback = (
            status is None
            or (status == HTTPStatus.BAD_REQUEST and is_task_not_exist(payload))
        )
        if need_fallback:
            for ek in enabled_keys:
                key_id = int(ek["id"])
                if key_id == chosen_key_id:
                    continue
                s, p = call_agnes_upstream("GET", f"/videos/{task_id}", ek["api_key"])
                if s is None:
                    continue
                status, payload = s, p
                chosen_key_id = key_id
                if not (s == HTTPStatus.BAD_REQUEST and is_task_not_exist(p)):
                    break

        if status is None:
            continue

        progress_raw = payload.get("progress", 0) if isinstance(payload, dict) else 0
        try:
            progress = int(progress_raw)
        except (TypeError, ValueError):
            progress = 0
        new_status = str(payload.get("status") or "") if isinstance(payload, dict) else ""
        prev_video_url = str(row["video_url"] or "") if "video_url" in row.keys() else ""
        video_url = extract_video_url(payload) if isinstance(payload, dict) else ""
        if not video_url:
            video_url = prev_video_url
        seconds = str(payload.get("seconds") or "") if isinstance(payload, dict) else ""
        model = str(payload.get("model") or row["model"] or "") if isinstance(payload, dict) else str(row["model"] or "")
        prompt = str(payload.get("prompt") or row["prompt"] or "") if isinstance(payload, dict) else str(row["prompt"] or "")
        last_error = ""
        if isinstance(payload, dict) and (new_status == "failed" or status >= 400):
            last_error = str(payload.get("message") or payload.get("error") or payload.get("code") or "").strip()

        updates.append({
            "row_id": int(row["id"]),
            "key_id": int(chosen_key_id),
            "model": model,
            "prompt": prompt,
            "status": new_status,
            "progress": progress,
            "video_url": video_url,
            "seconds": seconds,
            "last_error": last_error,
        })

    if not updates:
        return 0

    write_conn = get_db()
    try:
        begin_immediate_with_retry(write_conn)
        for u in updates:
            write_conn.execute(
                """
                UPDATE agnes_video_tasks
                SET api_key_id = ?, model = ?, prompt = ?, status = ?, progress = ?, video_url = ?, seconds = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (u["key_id"], u["model"], u["prompt"], u["status"], u["progress"], u["video_url"], u["seconds"], u["last_error"], now, u["row_id"]),
            )
            write_conn.execute(
                "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                (now, u["key_id"]),
            )
        write_conn.commit()
        return len(updates)
    finally:
        write_conn.close()


def run_agnes_task_worker():
    """Background worker loop: refresh video task status periodically."""
    while True:
        try:
            refresh_agnes_tasks_once(limit=100)
        except Exception as exc:
            print(f"[AgnesWorker] refresh error: {exc}")
        time.sleep(AGNES_TASK_REFRESH_INTERVAL_SECONDS)
