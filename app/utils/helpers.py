"""
General-purpose helper functions.

- now_iso, quote_ident
- slugify, safe_filename
- URL extraction helpers
- clamp_float_value, clamp_int_value
- estimate_text_tokens_value, estimate_prompt_tokens_for_history
- merge_stream_text, extract_chat_reasoning_text
- generate_chat_task_id
- normalize_chat_session_title
- mask_api_key
"""
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _find_first_url(value, _depth=0):
    if _depth > 6:
        return ""
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("http://") or s.startswith("https://"):
            return s
        return ""
    if isinstance(value, list):
        for item in value:
            hit = _find_first_url(item, _depth + 1)
            if hit:
                return hit
        return ""
    if isinstance(value, dict):
        for key in ("video_url", "url", "download_url", "play_url"):
            hit = _find_first_url(value.get(key), _depth + 1)
            if hit:
                return hit
        for nested in value.values():
            hit = _find_first_url(nested, _depth + 1)
            if hit:
                return hit
    return ""


def extract_video_url(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("video_url", "videoUrl", "url", "download_url", "play_url"):
        hit = _find_first_url(payload.get(key))
        if hit:
            return hit
    for key in ("data", "result", "output", "outputs", "video", "videos"):
        if key in payload:
            hit = _find_first_url(payload.get(key))
            if hit:
                return hit
    return _find_first_url(payload)


def slugify(value: str) -> str:
    out = []
    for ch in value.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", "_"}:
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or f"product-{int(time.time())}"


def safe_filename(name: str) -> str:
    clean = "".join(ch for ch in name if ch.isalnum() or ch in {".", "-", "_"})
    clean = clean.strip(".")
    return clean or f"package-{int(time.time())}.zip"


def clamp_float_value(value, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def clamp_int_value(value, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def normalize_chat_session_title(value: str, fallback: str = "New Chat") -> str:
    title = str(value or "").strip()
    return title[:120] if title else fallback


def estimate_text_tokens_value(text: str) -> int:
    raw = str(text or "").strip()
    if not raw:
        return 0
    return max(1, (len(raw.encode("utf-8")) + 3) // 4)


def estimate_prompt_tokens_for_history(system_prompt: str, messages) -> int:
    total = 0
    prompt = str(system_prompt or "").strip()
    if prompt:
        total += estimate_text_tokens_value(prompt)
    for item in messages or []:
        total += estimate_text_tokens_value(item.get("content") or "")
        total += estimate_text_tokens_value(item.get("thinking_text") or "")
        total += 4
    return total


def merge_stream_text(existing: str, incoming: str) -> str:
    base = str(existing or "")
    chunk = str(incoming or "")
    if not chunk:
        return base
    if not base:
        return chunk
    if chunk.startswith(base):
        return chunk
    if base.endswith(chunk):
        return base
    return base + chunk


def extract_chat_reasoning_text(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("reasoning_content", "reasoning", "thinking", "reasoning_text", "thought"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def generate_chat_task_id() -> str:
    return f"chat_{int(time.time() * 1000)}_{secrets.token_hex(6)}"


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def json_safe_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    return str(value)
