"""
Chat token statistics worker — recalculates token usage from messages.
Processes sessions in batches to keep memory bounded.
"""
import time

from app.config import CHAT_TOKEN_REFRESH_INTERVAL_SECONDS, SERVER_RUNTIME
from app.db import get_db, begin_immediate_with_retry
from app.utils.helpers import estimate_text_tokens_value, estimate_prompt_tokens_for_history, now_iso

_BATCH_SIZE = 100  # Sessions per batch


def refresh_agnes_chat_token_stats_once() -> dict | None:
    """Recalculate token stats for all chat sessions (batched). Returns summary dict."""
    now = now_iso()
    conn = get_db()
    try:
        owner_stats = {}
        message_updates = []
        offset = 0
        total_sessions = 0

        while True:
            session_rows = conn.execute(
                "SELECT * FROM agnes_chat_sessions ORDER BY id ASC LIMIT ? OFFSET ?",
                (_BATCH_SIZE, offset),
            ).fetchall()
            if not session_rows:
                break
            total_sessions += len(session_rows)

            for session_row in session_rows:
                message_rows = conn.execute(
                    """
                    SELECT *
                    FROM agnes_chat_messages
                    WHERE session_id = ?
                    ORDER BY sequence_no ASC, id ASC
                    """,
                    (int(session_row["id"]),),
                ).fetchall()
                owner_key = str(session_row["owner_key"] or "guest:0")
                stats = owner_stats.setdefault(
                    owner_key,
                    {
                        "owner_key": owner_key,
                        "owner_role": session_row["owner_role"] or "guest",
                        "owner_name": session_row["owner_name"] or "guest",
                        "user_id": session_row["user_id"],
                        "session_count": 0,
                        "message_count": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                    },
                )
                stats["session_count"] += 1
                stats["message_count"] += len(message_rows)
                history = []
                for message_row in message_rows:
                    role = str(message_row["role"] or "")
                    content = str(message_row["content"] or "")
                    thinking_text = str(message_row["thinking_text"] or "")
                    if role == "assistant":
                        prompt_tokens = int(message_row["prompt_tokens"] or 0)
                        completion_tokens = int(message_row["completion_tokens"] or 0)
                        total_tokens = int(message_row["total_tokens"] or 0)
                        token_source = str(message_row["token_source"] or "").strip()
                        if prompt_tokens <= 0 or completion_tokens <= 0 or total_tokens <= 0:
                            prompt_tokens = estimate_prompt_tokens_for_history(session_row["system_prompt"] or "", history)
                            completion_tokens = estimate_text_tokens_value(content) + estimate_text_tokens_value(thinking_text)
                            total_tokens = prompt_tokens + completion_tokens
                            token_source = token_source or "estimated"
                            message_updates.append((prompt_tokens, completion_tokens, total_tokens, token_source, now, int(message_row["id"])))
                        elif not token_source:
                            token_source = "upstream"
                            message_updates.append((prompt_tokens, completion_tokens, total_tokens, token_source, now, int(message_row["id"])))
                        stats["input_tokens"] += prompt_tokens
                        stats["output_tokens"] += completion_tokens
                        stats["total_tokens"] += total_tokens
                    history.append({"role": role, "content": content, "thinking_text": thinking_text})

            offset += len(session_rows)

        # Write results in a single transaction
        begin_immediate_with_retry(conn)
        if message_updates:
            conn.executemany(
                """
                UPDATE agnes_chat_messages
                SET prompt_tokens = ?, completion_tokens = ?, total_tokens = ?, token_source = ?, updated_at = ?
                WHERE id = ?
                """,
                message_updates,
            )
        conn.execute("DELETE FROM agnes_chat_token_stats")
        for item in owner_stats.values():
            conn.execute(
                """
                INSERT INTO agnes_chat_token_stats (
                    owner_key, owner_role, owner_name, user_id,
                    session_count, message_count, input_tokens, output_tokens, total_tokens, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item["owner_key"], item["owner_role"], item["owner_name"], item["user_id"],
                 int(item["session_count"]), int(item["message_count"]),
                 int(item["input_tokens"]), int(item["output_tokens"]), int(item["total_tokens"]), now),
            )
        conn.commit()
        SERVER_RUNTIME["chat_token_refreshed_at"] = now
        return {"owners": len(owner_stats), "messages_updated": len(message_updates)}
    finally:
        conn.close()


def run_chat_token_worker():
    """Background worker loop: refresh chat token stats periodically."""
    while True:
        try:
            refresh_agnes_chat_token_stats_once()
        except Exception as exc:
            print(f"[ChatTokenWorker] refresh error: {exc}")
        time.sleep(CHAT_TOKEN_REFRESH_INTERVAL_SECONDS)
