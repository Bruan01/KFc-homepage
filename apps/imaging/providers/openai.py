from __future__ import annotations

import base64
import binascii
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
USER_AGENT = "KFlow-Imaging/1.0"


class ImageProviderError(RuntimeError):
    """A normalized provider failure with enough metadata for safe diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider_error",
        status_code: int | None = None,
        error_code: str = "",
        error_type: str = "",
        request_id: str = "",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.error_code = error_code
        self.error_type = error_type
        self.request_id = request_id
        self.retryable = retryable

    def diagnostic_payload(self) -> dict:
        """Return non-secret structured details for administrator responses."""
        return {
            "error": str(self),
            "errorCategory": self.category,
            "httpStatus": self.status_code,
            "providerErrorCode": self.error_code or None,
            "providerErrorType": self.error_type or None,
            "requestId": self.request_id or None,
            "retryable": self.retryable,
        }


def normalize_openai_api_base_url(value: str) -> str:
    """Validate an OpenAI-compatible API root and add `/v1` to a bare origin."""
    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("API Base URL 必须是无账号、查询参数和片段的合法 HTTP/HTTPS 地址")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))


def _read_limited(response, limit: int, message: str) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise ImageProviderError(message, category="response_too_large")
        except (TypeError, ValueError):
            pass
    content = response.read(limit + 1)
    if len(content) > limit:
        raise ImageProviderError(message, category="response_too_large")
    return content


def _header(response, name: str) -> str:
    value = response.headers.get(name) if getattr(response, "headers", None) else ""
    return str(value or "").strip()


def _error_details(response) -> tuple[str, str, str]:
    fallback = str(getattr(response, "reason", "请求失败") or "请求失败")
    try:
        raw = response.read(MAX_ERROR_BYTES)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (AttributeError, OSError, TypeError, ValueError):
        return fallback, "", ""
    error = payload.get("error", payload) if isinstance(payload, dict) else payload
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("error") or fallback)
        code = str(error.get("code") or "")
        error_type = str(error.get("type") or "")
        return message, code, error_type
    return str(error or fallback), "", ""


def _http_error(exc: urllib.error.HTTPError) -> ImageProviderError:
    status_code = int(exc.code)
    message, error_code, error_type = _error_details(exc)
    request_id = _header(exc, "x-request-id") or _header(exc, "request-id") or _header(exc, "cf-ray")
    model_error = "model" in f"{error_code} {error_type} {message}".lower()
    if status_code in {401, 403}:
        category = "authentication"
    elif status_code == 404 and model_error:
        category = "model_not_available"
    elif status_code == 404:
        category = "endpoint_not_found"
    elif status_code == 429:
        category = "rate_limited"
    elif status_code in {408, 409, 425}:
        category = "temporary_failure"
    elif status_code >= 500:
        category = "upstream_failure"
    elif status_code == 400:
        category = "request_rejected"
    else:
        category = "http_error"
    retryable = status_code in {408, 409, 425, 429} or status_code >= 500
    details = [f"HTTP {status_code}"]
    if error_type:
        details.append(f"类型 {error_type}")
    if error_code:
        details.append(f"代码 {error_code}")
    if request_id:
        details.append(f"请求 ID {request_id}")
    return ImageProviderError(
        f"显影服务请求失败（{'，'.join(details)}）：{message}",
        category=category,
        status_code=status_code,
        error_code=error_code,
        error_type=error_type,
        request_id=request_id,
        retryable=retryable,
    )


@dataclass(frozen=True)
class OpenAIImagesClient:
    """Small OpenAI Images API client used by a configured provider."""

    base_url: str
    api_key: str
    timeout_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", normalize_openai_api_base_url(self.base_url))
        object.__setattr__(self, "api_key", str(self.api_key or "").strip())
        if not self.api_key:
            raise ImageProviderError(
                "该显影服务未配置 API Key。",
                category="configuration",
                retryable=False,
            )

    @property
    def models_endpoint(self) -> str:
        return f"{self.base_url}/models"

    @property
    def image_generation_endpoint(self) -> str:
        return f"{self.base_url}/images/generations"

    @property
    def image_edit_endpoint(self) -> str:
        return f"{self.base_url}/images/edits"

    def _request(self, request: urllib.request.Request, *, limit: int = MAX_JSON_BYTES) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return _read_limited(response, limit, "显影服务响应超过允许大小。")
        except urllib.error.HTTPError as exc:
            raise _http_error(exc) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ImageProviderError(
                "连接显影服务超时。",
                category="timeout",
                retryable=True,
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ImageProviderError(
                "无法连接显影服务，请检查 API Base URL、DNS 和网络状态。",
                category="network",
                retryable=True,
            ) from exc

    def _json_request(self, method: str, url: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method=method,
        )
        raw = self._request(request)
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImageProviderError(
                "显影服务返回了非 JSON 响应。",
                category="invalid_response",
                retryable=True,
            ) from exc
        if not isinstance(result, dict):
            raise ImageProviderError(
                "显影服务返回了无法识别的 JSON 结构。",
                category="invalid_response",
                retryable=True,
            )
        return result

    def check_model(self, model: str) -> dict:
        """Verify authentication and model visibility without generating an image."""
        payload = self._json_request("GET", self.models_endpoint)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ImageProviderError(
                "模型列表响应缺少 data 数组。",
                category="invalid_response",
                retryable=False,
            )
        model_ids = {
            str(row.get("id") or "").strip()
            for row in rows
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        available = model in model_ids
        if not available:
            raise ImageProviderError(
                f"当前 API Key 的模型列表中没有 {model}。",
                category="model_not_available",
                retryable=False,
            )
        return {
            "authenticated": True,
            "modelAvailable": True,
            "availableModelCount": len(model_ids),
            "modelsEndpoint": self.models_endpoint,
            "imageGenerationEndpoint": self.image_generation_endpoint,
        }

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        size: str,
        quality: str,
        output_format: str,
        references=(),
    ) -> bytes:
        """Generate one image, optionally using persisted reference images."""
        fields = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "output_format": output_format,
            "n": 1,
        }
        if references:
            payload = self._multipart_request(fields, references)
        else:
            payload = self._json_request("POST", self.image_generation_endpoint, fields)
        return self._decode_image_payload(payload)

    def _multipart_request(self, fields: dict, references) -> dict:
        boundary = f"kflow-{uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        for reference in references:
            filename = Path(str(getattr(reference, "original_name", "reference.png"))).name
            filename = filename.replace('"', "'").replace("\r", "").replace("\n", "") or "reference.png"
            content_type = str(getattr(reference, "content_type", "") or "application/octet-stream")
            with reference.image.open("rb") as handle:
                content = handle.read(MAX_REFERENCE_IMAGE_BYTES + 1)
            if len(content) > MAX_REFERENCE_IMAGE_BYTES:
                raise ImageProviderError("参考图片超过10MB限制", category="request_rejected", retryable=False)
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode(),
                    f"Content-Type: {content_type}\r\n\r\n".encode(),
                    content,
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            self.image_edit_endpoint,
            data=b"".join(chunks),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        raw = self._request(request)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImageProviderError(
                "显影服务返回了非 JSON 响应。",
                category="invalid_response",
                retryable=True,
            ) from exc
        if not isinstance(payload, dict):
            raise ImageProviderError(
                "显影服务返回了无法识别的 JSON 结构。",
                category="invalid_response",
                retryable=True,
            )
        return payload

    def _decode_image_payload(self, payload: dict) -> bytes:
        rows = payload.get("data")
        image = rows[0] if isinstance(rows, list) and rows else None
        if not isinstance(image, dict):
            raise ImageProviderError(
                "显影服务响应中没有可用的图片数据。",
                category="invalid_response",
                retryable=True,
            )
        encoded = image.get("b64_json")
        if encoded:
            raw_value = str(encoded)
            if raw_value.startswith("data:") and "," in raw_value:
                raw_value = raw_value.split(",", 1)[1]
            try:
                content = base64.b64decode(raw_value, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ImageProviderError(
                    "显影服务返回的 Base64 图片无法解码。",
                    category="invalid_response",
                    retryable=True,
                ) from exc
            if len(content) > MAX_IMAGE_BYTES:
                raise ImageProviderError("显影服务返回的图片过大。", category="response_too_large")
            return content
        image_url = image.get("url")
        if image_url:
            return self._download_image(str(image_url))
        raise ImageProviderError(
            "显影服务响应中没有 b64_json 或 url。",
            category="invalid_response",
            retryable=True,
        )

    def _download_image(self, image_url: str) -> bytes:
        parsed = urlsplit(image_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ImageProviderError("显影服务返回了不安全的图片地址。", category="invalid_response")
        headers = {"Accept": "image/*", "User-Agent": USER_AGENT}
        api_origin = urlsplit(self.base_url)
        if (parsed.scheme.lower(), parsed.netloc.lower()) == (api_origin.scheme.lower(), api_origin.netloc.lower()):
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(image_url, headers=headers, method="GET")
        return self._request(request, limit=MAX_IMAGE_BYTES)
