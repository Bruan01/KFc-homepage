"""
SSE (Server-Sent Events) parsing helpers for Agnes Chat streaming.
"""
import json


def parse_chat_sse_block(block_text: str) -> dict | None:
    """Parse a single SSE block from the Agnes chat upstream."""
    lines = [line for line in str(block_text or "").splitlines() if line.startswith("data:")]
    if not lines:
        return None
    data_text = "\n".join(line[5:].lstrip() for line in lines).strip()
    if not data_text:
        return None
    if data_text == "[DONE]":
        return {"done": True, "content": "", "thinking": "", "usage": None, "finish_reason": "", "error": ""}
    try:
        payload = json.loads(data_text)
    except Exception:
        return None
    choice = ((payload.get("choices") or [{}])[0]) if isinstance(payload, dict) else {}
    delta = choice.get("delta") if isinstance(choice, dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    content = ""
    if isinstance(delta, dict):
        content = str(delta.get("content") or "")
    if not content and isinstance(message, dict):
        content = str(message.get("content") or "")
    thinking = ""
    for src in (delta if isinstance(delta, dict) else {}, message if isinstance(message, dict) else {}, choice, payload):
        if not isinstance(src, dict):
            continue
        thinking = str(
            src.get("reasoning_content")
            or src.get("reasoning")
            or src.get("thinking")
            or src.get("reasoning_text")
            or ""
        ).strip()
        if thinking:
            break
    error_text = ""
    if isinstance(payload, dict):
        if isinstance(payload.get("error"), str):
            error_text = payload.get("error") or ""
        elif isinstance(payload.get("error"), dict):
            error_text = str(payload.get("error", {}).get("message") or "")
    return {
        "done": False,
        "content": content,
        "thinking": thinking,
        "usage": payload.get("usage") if isinstance(payload, dict) else None,
        "finish_reason": str(choice.get("finish_reason") or "") if isinstance(choice, dict) else "",
        "error": error_text,
    }
