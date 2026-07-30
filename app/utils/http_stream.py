"""
Shared streaming file-response helper with HTTP Range support.

Used by both static asset serving (video, material) and product download.
Streams in fixed-size chunks so a single request never loads the whole file
into memory — crucial for large upload packages (hundreds of MB).
"""
import re
from http import HTTPStatus
from pathlib import Path

from app.config import STREAM_CHUNK_SIZE


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def parse_range_header(header: str, file_size: int):
    """Parse an HTTP Range header. Returns (start, end) inclusive, or None.

    Returns None if the header is absent or empty. Raises ValueError on
    malformed / unsatisfiable ranges — callers must translate to 416.
    """
    text = (header or "").strip()
    if not text:
        return None
    match = _RANGE_RE.fullmatch(text)
    if not match:
        raise ValueError("invalid range header")
    start_text, end_text = match.groups()
    if start_text == "":
        suffix_size = int(end_text) if end_text else 0
        if suffix_size <= 0:
            raise ValueError("invalid suffix range")
        start = max(file_size - suffix_size, 0)
        end = file_size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    end = min(end, file_size - 1)
    if start >= file_size or start > end:
        raise ValueError("range out of bounds")
    return start, end


def stream_file_response(
    handler,
    target: Path,
    mime: str,
    cache_control: str = "",
    extra_headers=None,
):
    """Stream a file with Range support. Uses fixed-size chunks.

    Range parsing errors send 416 with a Content-Range: bytes */size header.
    Missing / empty Range serves the full file with status 200.
    """
    file_size = target.stat().st_size
    range_header = handler.headers.get("Range", "")

    try:
        parsed = parse_range_header(range_header, file_size)
    except ValueError:
        handler.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        handler.send_header("Content-Range", f"bytes */{file_size}")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return

    if parsed is None:
        start, end = 0, file_size - 1
        status = HTTPStatus.OK
    else:
        start, end = parsed
        status = HTTPStatus.PARTIAL_CONTENT

    content_length = end - start + 1
    handler.send_response(status)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(content_length))
    handler.send_header("Accept-Ranges", "bytes")
    if cache_control:
        handler.send_header("Cache-Control", cache_control)
    if status == HTTPStatus.PARTIAL_CONTENT:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
    if extra_headers:
        for key, value in extra_headers:
            handler.send_header(key, value)
    handler.end_headers()

    with target.open("rb") as f:
        f.seek(start)
        remaining = content_length
        while remaining > 0:
            chunk = f.read(min(STREAM_CHUNK_SIZE, remaining))
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return
            remaining -= len(chunk)
