"""
Static file serving handler.
"""
import mimetypes
from http import HTTPStatus
from pathlib import Path

from app.config import STATIC_DIR


def serve_static(handler, path: str) -> None:
    """Serve a file from the static directory, or 404/403."""
    if path == "/":
        rel = "index.html"
    elif path == "/admin":
        rel = "admin.html"
    elif path == "/admin/model-control":
        rel = "admin-model-control.html"
    elif path == "/admin/bigscreen":
        rel = "admin-bigscreen.html"
    elif path == "/admin/login":
        rel = "admin-login.html"
    elif path == "/admin/register":
        rel = "admin-register.html"
    elif path == "/login":
        rel = "user-login.html"
    elif path == "/account":
        rel = "account.html"
    elif path == "/agnes-chat":
        rel = "agnes-chat.html"
    elif path == "/agnes-video-v2":
        rel = "agnes-video-v2.html"
    elif path == "/cardloom":
        rel = "cardloom_official_website.html"
    elif path.startswith("/product/"):
        rel = "product.html"
    else:
        rel = path.lstrip("/")

    target = (STATIC_DIR / rel).resolve()
    try:
        target.relative_to(STATIC_DIR.resolve())
    except ValueError:
        handler.send_error(HTTPStatus.FORBIDDEN)
        return

    if not target.exists() or not target.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND)
        return

    mime, _ = mimetypes.guess_type(str(target))
    mime = mime or "application/octet-stream"
    if mime.startswith("text/") and "charset=" not in mime.lower():
        mime = f"{mime}; charset=utf-8"

    with target.open("rb") as f:
        data = f.read()

    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
