"""
Agnes Chat API handlers — sessions, messages, streaming, and model config.
"""
import json
from http import HTTPStatus

from app.config import AGNES_CHAT_MODEL_CONTROL_DEFAULTS
from app.db import get_db
from app.utils.helpers import (
    clamp_float_value,
    clamp_int_value,
    estimate_text_tokens_value,
    generate_chat_task_id,
    now_iso,
    normalize_chat_session_title,
)


# ── Sessions ──


def handle_agnes_chat_sessions_get(handler):
    """GET /api/agnes/chat-sessions — list chat sessions for current user."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    owner = handler.get_current_agnes_owner(auth_ctx)

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM agnes_chat_sessions
            WHERE owner_key = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (owner["owner_key"],),
        ).fetchall()
        items = [handler.serialize_chat_session(conn, row) for row in rows]
    finally:
        conn.close()
    handler.send_json({"items": items})


def handle_agnes_chat_sessions_create(handler):
    """POST /api/agnes/chat-sessions — create a new chat session."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    owner = handler.get_current_agnes_owner(auth_ctx)

    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return

    title = str(body.get("title") or "").strip() or "New Chat"

    config = handler.get_effective_chat_model_config()
    model = str(body.get("model") or config["default_model"] or AGNES_CHAT_MODEL_CONTROL_DEFAULTS["default_model"])
    system_prompt = str(body.get("system_prompt") if "system_prompt" in body else body.get("systemPrompt") or config["default_system_prompt"] or "")
    enable_thinking = body.get("enable_thinking") if "enable_thinking" in body else body.get("enableThinking") if "enableThinking" in body else config.get("default_enable_thinking", True)

    conn = get_db()
    try:
        row = handler.create_chat_session_record(conn, owner, auth_ctx, title, {
            "model": model,
            "system_prompt": system_prompt,
            "enable_thinking": enable_thinking,
        })
        conn.commit()
        session_data = handler.serialize_chat_session(conn, row)
    finally:
        conn.close()

    handler.send_json({"ok": True, "item": session_data}, status=HTTPStatus.CREATED)


# ── Chat completion (SSE streaming) ──


def handle_agnes_chat_create(handler):
    """
    POST /api/agnes/chat — create a chat message and start upstream streaming.
    For SSE: sends the full session with messages so the client can display history.
    """
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    owner = handler.get_current_agnes_owner(auth_ctx)

    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return

    session_id = body.get("session_id")
    if session_id is not None:
        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            handler.send_json({"error": "invalid session_id"}, status=HTTPStatus.BAD_REQUEST)
            return

    # Accept both { content } and { messages } formats (frontend sends messages[])
    content = (body.get("content") or "").strip()
    if not content:
        messages_raw = body.get("messages")
        if isinstance(messages_raw, list):
            for msg in reversed(messages_raw):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = (msg.get("content") or "").strip()
                    if content:
                        break
    if not content:
        handler.send_json({"error": "content required"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        # Resolve session
        if session_id:
            session_row = handler.get_chat_session_row_for_owner(conn, session_id, owner["owner_key"])
            if not session_row:
                handler.send_json({"error": "session not found"}, status=HTTPStatus.NOT_FOUND)
                return
            new_title = False
        else:
            title = content[:80]
            session_row = handler.create_chat_session_record(conn, owner, auth_ctx, title, body)
            session_id = int(session_row["id"])
            new_title = True

        # Update title from first message if still default
        if not new_title and (session_row["title"] or "").strip() in ("", "New Chat"):
            handler.update_chat_session_record(conn, session_row, content[:80], body)

        # Build history from existing messages
        message_rows = conn.execute(
            """
            SELECT * FROM agnes_chat_messages
            WHERE session_id = ?
            ORDER BY sequence_no ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        messages = []
        for msg in message_rows:
            messages.append({
                "role": msg["role"] or "",
                "content": msg["content"] or "",
            })

        # Check token budget
        config = handler.get_effective_chat_model_config(conn)
        system_prompt = str(
            body.get("system_prompt") if "system_prompt" in body
            else body.get("systemPrompt") if "systemPrompt" in body
            else session_row["system_prompt"] or config["default_system_prompt"] or ""
        )
        model = str(body.get("model") or session_row["model"] or config["default_model"] or "agnes-2.0-flash")
        enable_thinking = bool(
            body.get("enable_thinking") if "enable_thinking" in body
            else body.get("enableThinking") if "enableThinking" in body
            else session_row["enable_thinking"] if "enable_thinking" in session_row.keys()
            else config.get("default_enable_thinking", True)
        )
        context_limit = int(config.get("context_window_messages", 12))
        thinking_limit = int(config.get("thinking_context_window_messages", 8))
        actual_limit = thinking_limit if enable_thinking else context_limit

        if len(messages) >= actual_limit:
            summary_max_chars = int(config.get("thinking_summary_max_chars", 1200)) if enable_thinking else int(config.get("summary_max_chars", 1800))
            summary_max_lines = int(config.get("summary_max_lines", 16))
            retain_thinking = bool(config.get("retain_thinking_on_empty_content", True))
            messages = _summarize_history(session_row, messages, body, actual_limit, summary_max_chars, summary_max_lines, retain_thinking)

        # Add user message
        user_msg_id = handler.create_chat_message_record(
            conn, session_id, "user", content, "",
            0, 0, 0, "", "", "completed", "", "",
        )

        # Build upstream payload
        upstream_messages = []
        if system_prompt:
            upstream_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            entry = {"role": msg["role"], "content": msg["content"]}
            if msg.get("thinking_text"):
                entry["reasoning_content"] = msg["thinking_text"]
            upstream_messages.append(entry)
        upstream_messages.append({"role": "user", "content": content})

        upstream_payload = {
            "model": model,
            "messages": upstream_messages,
            "stream": True,
            "max_tokens": int(body.get("max_tokens") or config["default_max_tokens"] or 2048),
            "temperature": float(body.get("temperature") or config["default_temperature"] or 0.7),
        }

        # Enable thinking if requested (required by Agnes API)
        if enable_thinking:
            upstream_payload["chat_template_kwargs"] = {"enable_thinking": True}

        # Create assistant placeholder
        assistant_msg_id = handler.create_chat_message_record(
            conn, session_id, "assistant", "", "",
            0, 0, 0, "", "", "pending", "", "",
        )

        # Create task
        task_id = generate_chat_task_id()
        handler.create_chat_task_record(conn, task_id, session_id, user_msg_id, assistant_msg_id, owner, auth_ctx, model, upstream_payload)
        conn.commit()

        session_row = conn.execute(
            "SELECT * FROM agnes_chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        # Serialize before closing conn
        result = handler.serialize_chat_session(conn, session_row)
    finally:
        conn.close()

    handler.send_json(result)


# ── Model Config ──


def handle_admin_chat_model_config_get(handler):
    """GET /api/admin/chat-model-config"""
    if not handler.require_auth():
        return
    config = handler.get_effective_chat_model_config()
    handler.send_json(config)


def handle_admin_chat_model_config_update(handler):
    """POST /api/admin/chat-model-config"""
    sess = handler.require_level2_auth()
    if not sess:
        return
    _, admin = sess
    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return

    data, err = handler.validate_chat_model_config_payload(body)
    if err:
        handler.send_json({"error": err}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        row = handler.get_chat_model_config_row(conn)
        if row:
            conn.execute(
                """
                UPDATE agnes_chat_model_config
                SET default_model = ?, default_system_prompt = ?,
                    default_temperature = ?, default_max_tokens = ?,
                    default_enable_thinking = ?,
                    context_window_messages = ?, thinking_context_window_messages = ?,
                    summary_max_lines = ?, summary_max_chars = ?,
                    thinking_summary_max_chars = ?,
                    retain_thinking_on_empty_content = ?,
                    updated_at = ?, updated_by = ?
                WHERE id = 1
                """,
                (
                    data["default_model"], data["default_system_prompt"],
                    data["default_temperature"], data["default_max_tokens"],
                    1 if data["default_enable_thinking"] else 0,
                    data["context_window_messages"], data["thinking_context_window_messages"],
                    data["summary_max_lines"], data["summary_max_chars"],
                    data["thinking_summary_max_chars"],
                    1 if data["retain_thinking_on_empty_content"] else 0,
                    now_iso(), admin["username"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO agnes_chat_model_config (
                    default_model, default_system_prompt,
                    default_temperature, default_max_tokens,
                    default_enable_thinking,
                    context_window_messages, thinking_context_window_messages,
                    summary_max_lines, summary_max_chars,
                    thinking_summary_max_chars,
                    retain_thinking_on_empty_content,
                    updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["default_model"], data["default_system_prompt"],
                    data["default_temperature"], data["default_max_tokens"],
                    1 if data["default_enable_thinking"] else 0,
                    data["context_window_messages"], data["thinking_context_window_messages"],
                    data["summary_max_lines"], data["summary_max_chars"],
                    data["thinking_summary_max_chars"],
                    1 if data["retain_thinking_on_empty_content"] else 0,
                    now_iso(), admin["username"],
                ),
            )
        conn.commit()
    finally:
        conn.close()

    handler.send_json({"ok": True})


def handle_agnes_chat_config_get(handler):
    """GET /api/agnes/chat-config — public chat config endpoint."""
    config = handler.get_effective_chat_model_config()
    handler.send_json(config)


# ── History summarization ──


def handle_agnes_chat_session_delete(handler, path: str):
    """DELETE /api/agnes/chat-sessions/<id> — delete a chat session and its messages."""
    auth_ctx = handler.require_agnes_auth()
    if not auth_ctx:
        return
    owner = handler.get_current_agnes_owner(auth_ctx)
    parts = [p for p in path.split("/") if p]
    if len(parts) != 4:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        session_id = int(parts[3])
    except (ValueError, IndexError):
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM agnes_chat_sessions WHERE id = ? AND owner_key = ?",
            (session_id, owner["owner_key"]),
        ).fetchone()
        if not row:
            handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        conn.execute("DELETE FROM agnes_chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agnes_chat_tasks WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agnes_chat_sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True})


def _summarize_history(session_row, messages, body, limit, max_chars, max_lines, retain_thinking):
    """Summarize message history to stay within the context window."""
    if len(messages) < limit:
        return messages

    # Keep system messages, collapse the rest
    keep = []
    for i, msg in enumerate(messages):
        if msg["role"] == "system":
            keep.append(msg)
        elif len(keep) < limit - 1:
            keep.append(msg)

    return keep[-limit:]
