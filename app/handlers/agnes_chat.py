"""
Agnes Chat API handlers — sessions, messages, streaming, and model config.
"""
import json
from http import HTTPStatus

from app.config import (
    AGNES_CHAT_API_BASE,
    AGNES_CHAT_API_KEY,
    AGNES_CHAT_MODEL_CONTROL_DEFAULTS,
    AGNES_KEY_ROTATION_CURSOR,
    AGNES_KEY_ROTATION_LOCK,
)
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

        stream_mode = bool(body.get("stream", True))
        async_mode = bool(body.get("async"))

        if async_mode:
            # ── Async path: queue task for bg worker ──
            task_id = generate_chat_task_id()
            handler.create_chat_task_record(conn, task_id, session_id, user_msg_id, assistant_msg_id, owner, auth_ctx, model, upstream_payload)
            conn.commit()
            session_row = conn.execute(
                "SELECT * FROM agnes_chat_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            result = handler.serialize_chat_session(conn, session_row)
            conn.close()
            handler.send_json(result)
            return

        # ── Sync / SSE streaming path ──
        conn.commit()
        session_id_val = session_id
        assistant_msg_id_val = assistant_msg_id
    finally:
        conn.close()

    if not stream_mode:
        # Non-streaming: call upstream and return JSON
        from app.services.agnes_api import call_agnes_chat_upstream
        ust, up = call_agnes_chat_upstream(upstream_payload)
        if ust is None:
            handler.send_json({"error": "upstream unavailable"}, status=HTTPStatus.BAD_GATEWAY)
            return
        if ust >= 400:
            handler.send_json(up or {"error": f"upstream {ust}"}, status=HTTPStatus.BAD_GATEWAY)
            return
        assistant_content = up.get("choices",[{}])[0].get("message",{}).get("content","")
        _save_assistant_msg(assistant_msg_id_val, assistant_content, "", session_id_val)
        handler.send_json(up)
        return

    # ── SSE streaming ──
    from app.services.agnes_api import open_agnes_chat_upstream_stream
    from app.utils.helpers import merge_stream_text

    # Pick API key (use config module to avoid UnboundLocalError)
    api_key = AGNES_CHAT_API_KEY
    import app.config as _cfg
    kconn = get_db()
    try:
        rows = kconn.execute("SELECT api_key FROM agnes_api_keys WHERE enabled=1 ORDER BY id ASC").fetchall()
        if rows:
            with _cfg.AGNES_KEY_ROTATION_LOCK:
                idx = _cfg.AGNES_KEY_ROTATION_CURSOR % len(rows)
                api_key = str(rows[idx]["api_key"] or "").strip() or api_key
                _cfg.AGNES_KEY_ROTATION_CURSOR = (_cfg.AGNES_KEY_ROTATION_CURSOR + 1) % len(rows)
    finally:
        kconn.close()

    ust, uct, ustream, uerr = open_agnes_chat_upstream_stream(upstream_payload, api_key=api_key)
    if ust is None or ustream is None:
        handler.send_json({"error": uerr.get("error","upstream unavailable") if isinstance(uerr,dict) else "upstream unavailable"}, status=HTTPStatus.BAD_GATEWAY)
        return

    handler.send_sse_headers()

    final_content = ""
    final_thinking = ""

    try:
        if "text/event-stream" in (uct or ""):
            from app.utils.sse import parse_chat_sse_block
            sse_tail = ""
            while True:
                chunk = ustream.read(8192)
                if not chunk:
                    break
                sse_tail += chunk.decode("utf-8", errors="replace")
                blocks = sse_tail.split("\n\n")
                sse_tail = blocks.pop() or ""
                for block in blocks:
                    # Pass through SSE block (upstream already has "data: " prefix)
                    handler.wfile.write(f"{block}\n\n".encode("utf-8"))
                    handler.wfile.flush()
                    # Parse locally to track final content
                    parsed = parse_chat_sse_block(block)
                    if not parsed:
                        continue
                    if parsed.get("content"):
                        final_content = merge_stream_text(final_content, parsed["content"])
                    if parsed.get("thinking"):
                        final_thinking = merge_stream_text(final_thinking, parsed["thinking"])
        else:
            raw = ustream.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            dump = json.dumps({"delta": text})
            handler.wfile.write(f"data: {dump}\n\n".encode("utf-8"))
            handler.wfile.flush()
            final_content = text
    except Exception as exc:
        dump = json.dumps({"error": str(exc)})
        handler.wfile.write(f"data: {dump}\n\n".encode("utf-8"))
        handler.wfile.flush()
    finally:
        try:
            ustream.close()
        except Exception:
            pass

    handler.wfile.write("data: [DONE]\n\n".encode("utf-8"))
    handler.wfile.flush()

    # Persist final result
    _save_assistant_msg(assistant_msg_id_val, final_content, final_thinking, session_id_val)


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
        # Must delete in order: tasks first (FK to messages), then messages, then session
        conn.execute("DELETE FROM agnes_chat_tasks WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agnes_chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agnes_chat_sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True})


def _save_assistant_msg(assistant_msg_id, content, thinking, session_id):
    """Update assistant message with final content after streaming completes."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE agnes_chat_messages SET content=?, thinking_text=?, status='completed', updated_at=? WHERE id=?",
            (content, thinking, now_iso(), assistant_msg_id),
        )
        conn.execute(
            "UPDATE agnes_chat_sessions SET updated_at=? WHERE id=?",
            (now_iso(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


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
