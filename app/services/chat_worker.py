"""
Chat task processing worker — polls queued tasks, streams from upstream, writes results.
"""
import json
import time

from app.config import AGNES_CHAT_API_KEY, AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS, AGNES_KEY_ROTATION_LOCK, AGNES_KEY_ROTATION_CURSOR
from app.db import get_db
from app.services.agnes_api import open_agnes_chat_upstream_stream
from app.utils.helpers import merge_stream_text, extract_chat_reasoning_text, estimate_text_tokens_value, estimate_prompt_tokens_for_history, now_iso
from app.utils.sse import parse_chat_sse_block
from app.db import begin_immediate_with_retry


def claim_next_agnes_chat_task():
    """Claim one queued chat task (atomic). Returns task dict or None."""
    conn = get_db()
    try:
        begin_immediate_with_retry(conn)
        row = conn.execute(
            """
            SELECT *
            FROM agnes_chat_tasks
            WHERE status = 'queued'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.commit()
            return None
        now = now_iso()
        cur = conn.execute(
            """
            UPDATE agnes_chat_tasks
            SET status = 'in_progress',
                attempts = attempts + 1,
                started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (now, now, int(row["id"])),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return None
        if row["assistant_message_id"]:
            conn.execute(
                """
                UPDATE agnes_chat_messages
                SET status = 'in_progress', updated_at = ?
                WHERE id = ?
                """,
                (now, int(row["assistant_message_id"])),
            )
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def update_agnes_chat_task_state(
    task_row_id: int,
    assistant_message_id: int | None,
    *,
    status: str,
    content: str = "",
    thinking: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    finish_reason: str = "",
    error_text: str = "",
    api_key_id=None,
    completed: bool = False,
):
    """Update chat task and associated message state."""
    now = now_iso()
    conn = get_db()
    try:
        params = [
            status,
            content or "",
            thinking or "",
            int(prompt_tokens or 0),
            int(completion_tokens or 0),
            int(total_tokens or 0),
            finish_reason or "",
            error_text or "",
            now,
        ]
        sql = """
            UPDATE agnes_chat_tasks
            SET status = ?,
                response_content = ?,
                response_thinking = ?,
                prompt_tokens = ?,
                completion_tokens = ?,
                total_tokens = ?,
                finish_reason = ?,
                error_text = ?,
                updated_at = ?
        """
        if api_key_id is not None:
            sql += ", api_key_id = ?"
            params.append(api_key_id)
        if completed:
            sql += ", completed_at = ?"
            params.append(now)
        sql += " WHERE id = ?"
        params.append(int(task_row_id))
        conn.execute(sql, tuple(params))
        if assistant_message_id:
            conn.execute(
                """
                UPDATE agnes_chat_messages
                SET content = ?,
                    thinking_text = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    total_tokens = ?,
                    token_source = ?,
                    status = ?,
                    error_text = ?,
                    finish_reason = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    content or "",
                    thinking or "",
                    int(prompt_tokens or 0),
                    int(completion_tokens or 0),
                    int(total_tokens or 0),
                    "upstream" if (prompt_tokens or completion_tokens or total_tokens) else "",
                    status,
                    error_text or "",
                    finish_reason or "",
                    now,
                    int(assistant_message_id),
                ),
            )
            conn.execute(
                """
                UPDATE agnes_chat_sessions
                SET updated_at = ?
                WHERE id = (
                    SELECT session_id FROM agnes_chat_messages WHERE id = ?
                )
                """,
                (now, int(assistant_message_id)),
            )
        conn.commit()
    finally:
        conn.close()


def process_agnes_chat_task(task: dict):
    """Process a single chat task: call upstream, stream response, update DB."""
    task_row_id = int(task.get("id") or 0)
    assistant_message_id = int(task.get("assistant_message_id") or 0) or None
    task_id = str(task.get("task_id") or "").strip()
    raw_payload = str(task.get("request_payload") or "").strip()
    if not task_row_id or not task_id or not raw_payload:
        update_agnes_chat_task_state(
            task_row_id, assistant_message_id,
            status="failed", error_text="invalid chat task payload", completed=True,
        )
        return

    try:
        payload = json.loads(raw_payload)
    except Exception:
        update_agnes_chat_task_state(
            task_row_id, assistant_message_id,
            status="failed", error_text="invalid chat task payload", completed=True,
        )
        return

    # Pick API key
    conn = get_db()
    try:
        api_key_id, api_key = _pick_agnes_chat_api_key(conn)
        if not api_key:
            update_agnes_chat_task_state(
                task_row_id, assistant_message_id,
                status="failed", error_text="agnes chat api key not configured", completed=True,
            )
            return
        if api_key_id is not None:
            conn.execute(
                "UPDATE agnes_api_keys SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                (now_iso(), int(api_key_id)),
            )
            conn.commit()
    finally:
        conn.close()

    status, ctype, upstream_resp, err_payload = open_agnes_chat_upstream_stream(payload, api_key=api_key)
    if status is None:
        update_agnes_chat_task_state(
            task_row_id, assistant_message_id,
            status="failed",
            error_text=str((err_payload or {}).get("error") or (err_payload or {}).get("detail") or "upstream unavailable"),
            api_key_id=api_key_id, completed=True,
        )
        return
    if upstream_resp is None:
        detail = ""
        if isinstance(err_payload, dict):
            detail = str(
                err_payload.get("error") or err_payload.get("detail")
                or err_payload.get("message") or err_payload.get("raw") or ""
            ).strip()
        update_agnes_chat_task_state(
            task_row_id, assistant_message_id,
            status="failed",
            error_text=detail or f"upstream status {status}",
            api_key_id=api_key_id, completed=True,
        )
        return

    final_content = ""
    final_thinking = ""
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    finish_reason = ""
    error_text = ""
    last_flush_at = 0.0

    try:
        if "text/event-stream" in (ctype or ""):
            sse_tail = ""
            while True:
                chunk = upstream_resp.read(8192)
                if not chunk:
                    break
                sse_tail += chunk.decode("utf-8", errors="replace")
                blocks = sse_tail.split("\n\n")
                sse_tail = blocks.pop() or ""
                for block in blocks:
                    parsed = parse_chat_sse_block(block)
                    if not parsed:
                        continue
                    if parsed.get("error"):
                        error_text = str(parsed.get("error") or "").strip()
                    if parsed.get("content"):
                        final_content = merge_stream_text(final_content, parsed.get("content") or "")
                    if parsed.get("thinking"):
                        final_thinking = merge_stream_text(final_thinking, parsed.get("thinking") or "")
                    if parsed.get("usage"):
                        usage = parsed.get("usage") or {}
                        prompt_tokens = int(usage.get("prompt_tokens") or 0)
                        completion_tokens = int(usage.get("completion_tokens") or 0)
                        total_tokens = int(usage.get("total_tokens") or 0)
                    if parsed.get("finish_reason"):
                        finish_reason = str(parsed.get("finish_reason") or "")
                    now_ts = time.time()
                    if now_ts - last_flush_at >= 0.6:
                        update_agnes_chat_task_state(
                            task_row_id, assistant_message_id,
                            status="in_progress",
                            content=final_content, thinking=final_thinking,
                            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                            total_tokens=total_tokens, finish_reason=finish_reason,
                            error_text=error_text, api_key_id=api_key_id,
                        )
                        last_flush_at = now_ts
            if sse_tail.strip():
                parsed = parse_chat_sse_block(sse_tail)
                if parsed:
                    if parsed.get("error"):
                        error_text = str(parsed.get("error") or "").strip()
                    if parsed.get("content"):
                        final_content = merge_stream_text(final_content, parsed.get("content") or "")
                    if parsed.get("thinking"):
                        final_thinking = merge_stream_text(final_thinking, parsed.get("thinking") or "")
                    if parsed.get("usage"):
                        usage = parsed.get("usage") or {}
                        prompt_tokens = int(usage.get("prompt_tokens") or 0)
                        completion_tokens = int(usage.get("completion_tokens") or 0)
                        total_tokens = int(usage.get("total_tokens") or 0)
                    if parsed.get("finish_reason"):
                        finish_reason = str(parsed.get("finish_reason") or "")
        else:
            raw = upstream_resp.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            parsed = {}
            if text:
                if "application/json" in (ctype or ""):
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = {"raw": text}
                else:
                    parsed = {"raw": text}
            if isinstance(parsed, dict):
                choice = ((parsed.get("choices") or [{}])[0]) if isinstance(parsed, dict) else {}
                message = choice.get("message", {}) if isinstance(choice, dict) else {}
                final_content = str((message or {}).get("content") or "")
                final_thinking = (
                    extract_chat_reasoning_text(message)
                    or extract_chat_reasoning_text(choice)
                    or extract_chat_reasoning_text(parsed)
                )
                usage = parsed.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or 0)
                finish_reason = str(choice.get("finish_reason") or "")
                if isinstance(parsed.get("error"), dict):
                    error_text = str(parsed.get("error", {}).get("message") or "")
                elif isinstance(parsed.get("error"), str):
                    error_text = str(parsed.get("error") or "")
            if status >= 400:
                update_agnes_chat_task_state(
                    task_row_id, assistant_message_id,
                    status="failed",
                    content=final_content, thinking=final_thinking,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    total_tokens=total_tokens, finish_reason=finish_reason,
                    error_text=error_text or f"upstream status {status}",
                    api_key_id=api_key_id, completed=True,
                )
                return
    except Exception as exc:
        update_agnes_chat_task_state(
            task_row_id, assistant_message_id,
            status="failed",
            content=final_content, thinking=final_thinking,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=total_tokens, finish_reason=finish_reason,
            error_text=str(exc), api_key_id=api_key_id, completed=True,
        )
        return
    finally:
        try:
            upstream_resp.close()
        except Exception:
            pass

    if not final_content.strip() and final_thinking.strip():
        final_content = "本次响应仅返回思考过程，未收到最终答复。"
    if not final_content.strip() and not final_thinking.strip():
        update_agnes_chat_task_state(
            task_row_id, assistant_message_id,
            status="failed",
            error_text=error_text or "stream ended without valid content",
            api_key_id=api_key_id, completed=True,
        )
        return

    update_agnes_chat_task_state(
        task_row_id, assistant_message_id,
        status="completed",
        content=final_content, thinking=final_thinking,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        total_tokens=total_tokens, finish_reason=finish_reason,
        error_text="", api_key_id=api_key_id, completed=True,
    )


def run_agnes_chat_task_worker(worker_name: str):
    """Background worker loop: poll and process chat tasks with adaptive backoff."""
    idle_sleep = 0.0  # start at min, no sleep first time
    while True:
        try:
            task = claim_next_agnes_chat_task()
            if not task:
                # Adaptive backoff: 1s -> 2s -> 4s -> 8s -> 10s (max)
                if idle_sleep == 0.0:
                    idle_sleep = AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS
                else:
                    idle_sleep = min(idle_sleep * 2, 10.0)
                time.sleep(idle_sleep)
                continue
            idle_sleep = 0.0  # reset on success
            process_agnes_chat_task(task)
        except Exception as exc:
            print(f"[AgnesChatWorker:{worker_name}] task error: {exc}")
            time.sleep(AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS)

def _pick_agnes_chat_api_key(conn):
    """Pick the next Agnes chat API key (round-robin) or fallback to env key."""
    import app.config as cfg
    rows = conn.execute("SELECT id, api_key FROM agnes_api_keys WHERE enabled = 1 ORDER BY id ASC").fetchall()
    if rows:
        with cfg.AGNES_KEY_ROTATION_LOCK:
            idx = cfg.AGNES_KEY_ROTATION_CURSOR % len(rows)
            row = rows[idx]
            cfg.AGNES_KEY_ROTATION_CURSOR = (cfg.AGNES_KEY_ROTATION_CURSOR + 1) % len(rows)
        return int(row["id"]), str(row["api_key"] or "").strip()
    fallback_key = cfg.AGNES_CHAT_API_KEY.strip()
    return None, fallback_key
