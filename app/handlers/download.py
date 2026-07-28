"""
Download handler — file download with quota/access control.

Streams the file with HTTP Range support so a single request never buffers
the whole package in memory. Access control / accounting all happens before
the byte stream starts; the transfer itself is a plain chunked read.
"""
import mimetypes
from http import HTTPStatus
from urllib.parse import parse_qs, quote, urlparse

from app.config import BASE_DIR
from app.db import get_db
from app.services.points import account_payload, active_entitlement, product_download_cost
from app.utils.helpers import now_iso
from app.utils.http_stream import stream_file_response


def _resolve_download(conn, key: str, is_admin: bool, pkg_id):
    """Look up product + package file for the given slug-or-id and optional pkg id."""
    if key.isdigit():
        base = "SELECT * FROM products WHERE id = ?"
        args = (int(key),)
    else:
        base = "SELECT * FROM products WHERE slug = ?"
        args = (key,)
    if not is_admin:
        base += " AND status = 'published'"
    row = conn.execute(base, args).fetchone()
    if not row:
        return None, None, None, None
    file_name = row["file_name"]
    file_path_str = row["file_path"]
    file_size = row["file_size"]
    if pkg_id:
        pkg = conn.execute(
            "SELECT * FROM product_packages WHERE id = ? AND product_id = ?",
            (pkg_id, row["id"]),
        ).fetchone()
        if pkg and pkg["file_path"]:
            file_name = pkg["file_name"] or file_name
            file_path_str = pkg["file_path"]
            file_size = pkg["file_size"]
    return row, file_name, file_path_str, file_size


def handle_download(handler, path: str):
    """GET /download/<slug>[?pkg=<id>] — stream file with authorization check."""
    parsed = urlparse(path)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2:
        handler.send_error(HTTPStatus.NOT_FOUND)
        return
    query = parse_qs(parsed.query)
    pkg_id = None
    try:
        pkg_id = int(query.get("pkg", [None])[0])
    except (TypeError, ValueError):
        pass

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
        row, file_name, file_path_str, _file_size = _resolve_download(
            conn, key, is_admin_download, pkg_id
        )
        if not row or not file_path_str:
            handler.send_error(HTTPStatus.NOT_FOUND)
            return

        file_path = (BASE_DIR / file_path_str).resolve()
        if not file_path.exists() or not file_path.is_file():
            handler.send_error(HTTPStatus.NOT_FOUND)
            return

        product_id = row["id"]
        is_range_request = bool(handler.headers.get("Range", "").strip())

        if is_admin_download:
            # Admin downloads don't count against user quota — log the first byte only.
            if not is_range_request:
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
            entitlement = active_entitlement(conn, int(user_id), int(product_id)) if existing and not approved else None

            if existing and not approved and not entitlement:
                cost = product_download_cost(conn, row)
                account = account_payload(conn, int(user_id))
                handler.send_json(
                    {
                        "error": "download quota used",
                        "canRedeemPoints": cost is not None,
                        "pointCost": cost,
                        "pointsBalance": account["balance"],
                        "productId": product_id,
                        "productName": row["name"],
                    },
                    status=HTTPStatus.FORBIDDEN,
                )
                return

            # Only account for the *first* byte-range of a transfer (i.e. no Range
            # header, or Range starting at 0). Range continuation requests would
            # otherwise multiply-count the same download and drain quota.
            if not is_range_request:
                conn.execute(
                    "INSERT INTO downloads (product_id, user_id, request_id, entitlement_id, downloaded_at, ip, user_agent) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        product_id,
                        user_id,
                        approved["id"] if approved else None,
                        entitlement["id"] if entitlement else None,
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
                elif entitlement:
                    remaining = max(0, int(entitlement["remaining_count"] or 0) - 1)
                    conn.execute(
                        "UPDATE download_entitlements SET remaining_count = ?, consumed_at = CASE WHEN ? = 0 THEN ? ELSE consumed_at END "
                        "WHERE id = ?",
                        (remaining, remaining, now_iso(), entitlement["id"]),
                    )
                conn.commit()
    finally:
        conn.close()

    mime, _ = mimetypes.guess_type(str(file_path))
    mime = mime or "application/octet-stream"
    filename = file_name or file_path.name
    # RFC 5987: encode non-ASCII filenames for Content-Disposition.
    disposition = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'
    stream_file_response(
        handler,
        file_path,
        mime,
        cache_control="private, no-store",
        extra_headers=[("Content-Disposition", disposition)],
    )
