"""
Public product listing and detail API handlers.
"""
from http import HTTPStatus
from urllib.parse import unquote, urlparse

from app.db import get_db
from app.utils.helpers import now_iso


def handle_public_products(handler):
    """GET /api/products — list published products with search/filter/sort."""
    parsed = urlparse(handler.path)
    query = parsed.query or ""
    params = {}
    if query:
        for pair in query.split("&"):
            if not pair:
                continue
            if "=" not in pair:
                continue
            key, val = pair.split("=", 1)
            params[key] = unquote(val)

    search = (params.get("q") or "").strip()
    category = (params.get("category") or "").strip()
    version = (params.get("version") or "").strip()
    tags_raw = (params.get("tags") or "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    sort = (params.get("sort") or "latest").strip()
    order_sql = "ORDER BY COALESCE(p.published_at, p.updated_at) DESC"
    if sort == "downloads":
        order_sql = "ORDER BY download_count DESC"
    elif sort == "name":
        order_sql = "ORDER BY p.name ASC"
    elif sort == "version":
        order_sql = "ORDER BY p.version DESC"

    clauses = ["p.status = 'published'"]
    values = []
    if search:
        like = f"%{search}%"
        clauses.append("(p.name LIKE ? OR p.summary LIKE ? OR p.description LIKE ? OR p.category LIKE ? OR p.tags LIKE ?)")
        values.extend([like, like, like, like, like])
    if category:
        clauses.append("p.category = ?")
        values.append(category)
    if version:
        clauses.append("p.version = ?")
        values.append(version)
    for tag in tags:
        clauses.append("p.tags LIKE ?")
        values.append(f"%{tag}%")

    where_sql = " AND ".join(clauses)
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT p.*, COUNT(d.id) as download_count
            FROM products p
            LEFT JOIN downloads d ON d.product_id = p.id
            WHERE {where_sql}
            GROUP BY p.id
            {order_sql}
            """
            .format(where_sql=where_sql, order_sql=order_sql),
            values,
        ).fetchall()
    finally:
        conn.close()

    handler.send_json({"items": [_product_row_dict(r) for r in rows]})


def handle_public_products_meta(handler):
    """GET /api/products/meta — list unique categories and tags."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category, tags FROM products WHERE status = 'published'"
        ).fetchall()
    finally:
        conn.close()

    categories = set()
    tags = set()
    for r in rows:
        category = (r["category"] or "").strip()
        if category:
            categories.add(category)
        raw_tags = (r["tags"] or "").split(",")
        for tag in raw_tags:
            tag = tag.strip()
            if tag:
                tags.add(tag)
    handler.send_json({"categories": sorted(categories), "tags": sorted(tags)})


def handle_public_product_detail(handler, path: str):
    """GET /api/products/<id|slug> — product detail with download state."""
    key = path.split("/api/products/", 1)[1].strip()
    if not key:
        handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        return

    admin_ctx = handler.get_session()
    admin_data = admin_ctx[1] if admin_ctx else None
    user_ctx = handler.get_user_session()
    user_id = user_ctx[1]["user_id"] if user_ctx else None

    conn = get_db()
    try:
        if key.isdigit():
            row = conn.execute(
                "SELECT * FROM products WHERE id = ? AND status = 'published'", (int(key),)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM products WHERE slug = ? AND status = 'published'", (key,)
            ).fetchone()
        if not row:
            handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        count = conn.execute("SELECT COUNT(*) FROM downloads WHERE product_id = ?", (row["id"],)).fetchone()[0]
        out = _product_row_dict(row)
        out["download_count"] = count
        out["requires_login"] = True
        out["can_download_now"] = False
        out["download_rule"] = "one-time-per-user"
        out["user_download_state"] = {
            "loggedIn": user_id is not None,
            "is_admin": False,
            "has_downloaded": False,
            "has_approved_request": False,
            "pending_request": False,
        }

        if admin_data:
            out["requires_login"] = False
            out["can_download_now"] = bool(row["file_path"])
            out["download_rule"] = "admin-unlimited"
            out["user_download_state"] = {
                "loggedIn": True,
                "is_admin": True,
                "username": admin_data.get("username", ""),
                "admin_level": int(admin_data.get("admin_level", 1)),
                "has_downloaded": False,
                "has_approved_request": False,
                "pending_request": False,
            }
        elif user_id is not None:
            done = conn.execute(
                "SELECT 1 FROM downloads WHERE product_id = ? AND user_id = ? LIMIT 1",
                (row["id"], user_id),
            ).fetchone()
            approved = conn.execute(
                """
                SELECT id FROM download_requests
                WHERE product_id = ? AND user_id = ? AND status = 'approved' AND consumed_at IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (row["id"], user_id),
            ).fetchone()
            pending = conn.execute(
                """
                SELECT 1 FROM download_requests
                WHERE product_id = ? AND user_id = ? AND status = 'pending'
                ORDER BY id DESC LIMIT 1
                """,
                (row["id"], user_id),
            ).fetchone()
            has_downloaded = done is not None
            has_approved = approved is not None
            out["can_download_now"] = (not has_downloaded) or has_approved
            out["user_download_state"] = {
                "loggedIn": True,
                "is_admin": False,
                "has_downloaded": has_downloaded,
                "has_approved_request": has_approved,
                "pending_request": pending is not None,
            }
    finally:
        conn.close()

    handler.send_json(out)


def handle_user_download_request(handler, path: str):
    """POST /api/products/<id>/request-download — submit a request for additional download."""
    sess = handler.require_user_auth()
    if not sess:
        return
    _, user = sess
    user_id = user["user_id"]

    key = path.split("/api/products/", 1)[1].rsplit("/request-download", 1)[0].strip()
    if not key:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    try:
        body = handler.read_json_body()
    except Exception:
        body = {}
    reason = (body.get("reason") or "").strip()

    conn = get_db()
    try:
        if key.isdigit():
            row = conn.execute(
                "SELECT * FROM products WHERE id = ? AND status = 'published'", (int(key),)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM products WHERE slug = ? AND status = 'published'", (key,)
            ).fetchone()
        if not row:
            handler.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)
            return

        product_id = row["id"]
        done = conn.execute(
            "SELECT 1 FROM downloads WHERE product_id = ? AND user_id = ? LIMIT 1",
            (product_id, user_id),
        ).fetchone()
        if not done:
            handler.send_json({"error": "user has not consumed first download yet"}, status=HTTPStatus.BAD_REQUEST)
            return

        pending = conn.execute(
            """
            SELECT id FROM download_requests
            WHERE user_id = ? AND product_id = ? AND status = 'pending'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, product_id),
        ).fetchone()
        if pending:
            handler.send_json({"error": "request already pending"}, status=HTTPStatus.CONFLICT)
            return

        conn.execute(
            """
            INSERT INTO download_requests (user_id, product_id, reason, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (user_id, product_id, reason[:1000], now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    handler.send_json({"ok": True, "message": "request submitted"})


def _product_row_dict(row):
    """Convert a product row to a JSON-safe dict."""
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "summary": row["summary"],
        "description": row["description"],
        "category": row["category"] if "category" in row.keys() else "",
        "tags": row["tags"] if "tags" in row.keys() else "",
        "announcement": row["announcement"] if "announcement" in row.keys() else "",
        "version": row["version"],
        "changelog": row["changelog"],
        "status": row["status"],
        "created_by": row["created_by"] if "created_by" in row.keys() else "",
        "file_name": row["file_name"],
        "file_path": row["file_path"],
        "file_size": row["file_size"],
        "file_sha256": row["file_sha256"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "published_at": row["published_at"],
        "download_count": row["download_count"] if "download_count" in row.keys() else 0,
        "download_url": f"/download/{row['slug']}",
    }
