"""
Agnes API upstream communication (Facade pattern).
Wraps all HTTP calls to the external Agnes API.
"""
import json
from http import HTTPStatus
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import AGNES_CHAT_API_BASE


def call_agnes_upstream(method: str, api_path: str, api_key: str, payload=None):
    """Generic upstream API call returning (status, parsed_response)."""
    base_url = "https://apihub.agnes-ai.com/v1"
    url = f"{base_url}{api_path}"
    body = None
    headers = {"Authorization": f"Bearer {api_key}"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=180) as resp:
            status = int(getattr(resp, "status", HTTPStatus.OK))
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
        ctype = (exc.headers.get("Content-Type") or "").lower()
    except URLError as exc:
        return None, {"error": "upstream unavailable", "detail": str(exc.reason)}
    except Exception as exc:
        return None, {"error": "upstream request failed", "detail": str(exc)}

    if not raw:
        return status, {}
    text = raw.decode("utf-8", errors="replace")
    if "application/json" in ctype:
        try:
            return status, json.loads(text)
        except Exception:
            return status, {"raw": text}
    return status, {"raw": text}


def call_agnes_chat_upstream(payload, api_key: str = ""):
    """Call chat completion (non-streaming). Returns (status, parsed_response)."""
    from app.config import AGNES_CHAT_API_KEY
    resolved_api_key = (api_key or AGNES_CHAT_API_KEY).strip()
    if not resolved_api_key:
        return None, {"error": "agnes chat api key not configured"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }
    req = Request(
        url=f"{AGNES_CHAT_API_BASE}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(req, timeout=180) as resp:
            status = int(getattr(resp, "status", HTTPStatus.OK))
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
        ctype = (exc.headers.get("Content-Type") or "").lower()
    except URLError as exc:
        return None, {"error": "upstream unavailable", "detail": str(exc.reason)}
    except Exception as exc:
        return None, {"error": "upstream request failed", "detail": str(exc)}

    if not raw:
        return status, {}
    text = raw.decode("utf-8", errors="replace")
    if "application/json" in ctype:
        try:
            return status, json.loads(text)
        except Exception:
            return status, {"raw": text}
    return status, {"raw": text}


def open_agnes_chat_upstream_stream(payload, api_key: str = ""):
    """Open a streaming connection to chat completion. Returns (status, content_type, response, error_payload)."""
    from app.config import AGNES_CHAT_API_KEY
    resolved_api_key = (api_key or AGNES_CHAT_API_KEY).strip()
    if not resolved_api_key:
        return None, None, None, {"error": "agnes chat api key not configured"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }
    req = Request(
        url=f"{AGNES_CHAT_API_BASE}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        resp = urlopen(req, timeout=180)
        status = int(getattr(resp, "status", HTTPStatus.OK))
        ctype = (resp.headers.get("Content-Type") or "").lower()
        return status, ctype, resp, None
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
        ctype = (exc.headers.get("Content-Type") or "").lower()
        text = raw.decode("utf-8", errors="replace") if raw else ""
        if "application/json" in ctype and text:
            try:
                return status, ctype, None, json.loads(text)
            except Exception:
                return status, ctype, None, {"raw": text}
        return status, ctype, None, {"raw": text} if text else {}
    except URLError as exc:
        return None, None, None, {"error": "upstream unavailable", "detail": str(exc.reason)}
    except Exception as exc:
        return None, None, None, {"error": "upstream request failed", "detail": str(exc)}


def is_task_not_exist(payload) -> bool:
    """Check if the upstream returned a 'task_not_exist' error."""
    if not isinstance(payload, dict):
        return False
    code = str(payload.get("code") or "").strip().lower()
    message = str(payload.get("message") or "").strip().lower()
    return code == "task_not_exist" or message == "task_not_exist"
