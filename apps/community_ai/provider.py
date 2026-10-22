"""Independent Chat Completions adapter. No imaging settings or credentials."""
import base64
import hashlib
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class ProviderError(ValueError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def _cipher():
    digest = hashlib.sha256(("kflow-community-ai:" + settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_key(value):
    return _cipher().encrypt(value.encode()).decode() if value else ""


def decrypt_key(value):
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, UnicodeError):
        raise ProviderError("小 K 的密钥无法解密，请重新保存 API Key") from None


def normalize_url(value):
    parsed = urlsplit(value.strip())
    try:
        parsed.port
    except ValueError:
        raise ValueError("API 地址端口无效") from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API 地址请输入不带账号、查询参数或片段的 HTTP/HTTPS 地址")
    path = parsed.path.rstrip("/") or "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("API 地址发生重定向，请直接填写服务商的最终接口地址")


def complete(config, messages):
    base = normalize_url(config.base_url)
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    key = decrypt_key(config.api_key_ciphertext)
    headers = {"Content-Type": "application/json", "User-Agent": "KFlow-Community-AI/1.0"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=json.dumps({"model": config.model, "messages": messages, "stream": False}, ensure_ascii=False).encode(), headers=headers, method="POST")
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=60) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ProviderError("模型返回内容过大，请检查接口配置")
    except urllib.error.HTTPError as exc:
        # Upstream bodies can echo credentials. Never persist or expose them.
        exc.close()
        if exc.code in {401, 403}:
            raise ProviderError("API 鉴权失败，请检查小 K 的 API Key 与模型权限") from None
        if exc.code == 404:
            raise ProviderError("API 接口或模型不存在，请检查地址与模型名称") from None
        raise ProviderError(f"模型服务暂时无法处理请求（HTTP {exc.code}）", retryable=exc.code == 429 or exc.code >= 500) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise ProviderError("模型服务连接失败或超时，请检查地址和服务状态", retryable=True) from None
    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "\n".join(part["text"] for part in content if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str))
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
    except (ValueError, KeyError, TypeError, IndexError, UnicodeError):
        raise ProviderError("模型未返回有效文字，请确认该接口支持文本对话") from None
    answer = content.strip()
    return answer if len(answer) <= 500 else answer[:499] + "…"
