"""
Download handler — file download with quota/access control.
"""
import mimetypes
from http import HTTPStatus
from pathlib import Path

from app.config import BASE_DIR
from app.db import get_db
from app.utils.helpers import now_iso


def handle_download(handler, path: str):
    """GET /download/<slug> — serve file with authorization check."""
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2:
        handler.send_error(HTTPStatus.NOT_FOUND)
        return

    admin_sess = handler.get_session()
    user_sess = handler.get_user_session()
    if not admin_sess and not user_sess:
        handler.send_json({"error": "login required before download"}, status=HTTPStatus.UNAUTHORIZED)
        return
    is_admin_download = admin_sess is not None
    user_id = None
    if user_sess:
        _, user_data = user_sess
        user_id = user_data["user_id"]

    key = parts[1]
    conn = get_db()
    try:
        if key.isdigit():
            if is_admin_download:
                row = conn.execute("SELECT * FROM products WHERE id = ?", (int(key),)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM products WHERE id = ? AND status = 'published'", (int(key),)
                ).fetchone()
        else:
            if is_admin_download:
                row = conn.execute("SELECT * FROM products WHERE slug = ?", (key,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM products WHERE slug = ? AND status = 'published'", (key,)
                ).fetchone()
        if not row or not row["file_path"]:
            handler.send_error(HTTPStatus.NOT_FOUND)
            return

        file_path = (BASE_DIR / row["file_path"]).resolve()
        if not file_path.exists() or not file_path.is_file():
            handler.send_error(HTTPStatus.NOT_FOUND)
            return

        product_id = row["id"]
        if is_admin_download:
            conn.execute(
                "INSERT INTO downloads (product_id, user_id, request_id, downloaded_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    product_id,
                    None,
                    None,
                    now_iso(),
                    handler.client_address[0],
                    handler.headers.get("User-Agent", ""),
                ),
            )
            conn.commit()
        else:
            existing = conn.execute(
                "SELECT * FROM downloads WHERE product_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
                (product_id, user_id),
            ).fetchone()
            approved = conn.execute(
                """
                SELECT * FROM download_requests
                WHERE product_id = ? AND user_id = ? AND status = 'approved' AND consumed_at IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (product_id, user_id),
            ).fetchone()

            if existing and not approved:
                handler.send_json(
                    {"error": "download quota used, submit request for additional download"},
                    status=HTTPStatus.FORBIDDEN,
                )
                return

            conn.execute(
                "INSERT INTO downloads (product_id, user_id, request_id, downloaded_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    product_id,
                    user_id,
                    approved["id"] if approved else None,
                    now_iso(),
                    handler.client_address[0],
                    handler.headers.get("User-Agent", ""),
                ),
            )
            if approved:
                conn.execute(
                    "UPDATE download_requests SET consumed_at = ? WHERE id = ?",
                    (now_iso(), approved["id"]),
                )
            conn.commit()
    finally:
        conn.close()

    mime, _ = mimetypes.guess_type(str(file_path))
    mime = mime or "application/octet-stream"
    filename = row["file_name"] or file_path.name
    with file_path.open("rb") as f:
        blob = f.read()

    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(blob)))
    handler.end_headers()
    handler.wfile.write(blob)
