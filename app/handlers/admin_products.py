"""
Admin product CRUD handlers — get, create, update, delete, upload, version rollback.
"""
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import unquote

from app.config import (
    ADMIN_USERNAME,
    ALLOWED_EXTENSIONS,
    BASE_DIR,
    LV1_AUTO_PROMOTE_PROJECT_COUNT,
    UPLOAD_DIR,
)
from app.services.session_store import session_get
from app.db import get_db, begin_immediate_with_retry
from app.utils.helpers import now_iso, slugify, safe_filename
from app.utils.upload_limits import get_effective_upload_limit_bytes

PLATFORM_OPTIONS = ("Windows", "macOS", "Linux")
ARCHITECTURE_OPTIONS = ("x64", "ARM64")


def _normalize_choices(value, allowed, field_name):
    if value is None:
        return None
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    selected = []
    for item in value:
        item = str(item).strip()
        if item and item not in selected:
            selected.append(item)
    invalid = [item for item in selected if item not in allowed]
    if invalid:
        raise ValueError(f"invalid {field_name}: {', '.join(invalid)}")
    return json.dumps(selected, ensure_ascii=False)


def _decode_choices(value):
    try:
        selected = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        selected = []
    return selected if isinstance(selected, list) else []


def _delete_product_graph(conn: sqlite3.Connection, product_id: int) -> None:
    """Delete a product and every row that still holds an FK to it."""
    request_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM publish_requests WHERE product_id = ?", (product_id,)).fetchall()
    ]
    if request_ids:
        placeholders = ",".join("?" for _ in request_ids)
        conn.execute(f"DELETE FROM publish_request_votes WHERE request_id IN ({placeholders})", request_ids)

    conn.execute("DELETE FROM publish_requests WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM download_requests WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM downloads WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM product_packages WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM product_versions WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM admin_upload_events WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM product_delete_requests WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


def handle_admin_products_get(handler, path: str):
    """GET /api/admin/products or /api/admin/products/<id>"""
    if not handler.require_auth():
        return
    # Parse path and query from the raw handler.path (which includes query string)
    from urllib.parse import urlparse, parse_qs
    full_url = handler.path  # includes query string
    parsed = urlparse(full_url)
    clean_path = parsed.path  # path without query
    query_params = parse_qs(parsed.query)

    parts = [p for p in clean_path.split("/") if p]
    conn = get_db()
    try:
        if len(parts) == 3:
            # Parse query params: q, status, page, page_size
            search_q = (query_params.get("q") or [""])[0].strip()
            status_filter = (query_params.get("status") or [""])[0].strip()
            try:
                page = max(1, int((query_params.get("page") or ["1"])[0]))
            except ValueError:
                page = 1
            try:
                page_size = max(1, min(100, int((query_params.get("page_size") or ["20"])[0])))
            except ValueError:
                page_size = 20

            where_clauses = []
            params = []

            if status_filter in ("draft", "published"):
                where_clauses.append("p.status = ?")
                params.append(status_filter)

            if search_q:
                like = f"%{search_q}%"
                where_clauses.append(
                    "(p.name LIKE ? OR p.slug LIKE ? OR p.summary LIKE ? OR p.tags LIKE ? OR p.category LIKE ?)"
                )
                params.extend([like, like, like, like, like])

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Count total matching (for frontend pagination)
            count_row = conn.execute(
                f"SELECT COUNT(*) FROM products p {where_sql}", params
            ).fetchone()
            total_count = count_row[0] if count_row else 0

            offset = (page - 1) * page_size
            rows = conn.execute(
                f"""
                SELECT p.*, COUNT(d.id) as download_count
                FROM products p
                LEFT JOIN downloads d ON d.product_id = p.id
                {where_sql}
                GROUP BY p.id
                ORDER BY p.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [page_size, offset],
            ).fetchall()
            # Batch-fetch packages for all products
            product_ids = [r["id"] for r in rows]
            pkg_map = {}
            if product_ids:
                placeholders = ",".join("?" for _ in product_ids)
                pkg_rows = conn.execute(
                    f"SELECT * FROM product_packages WHERE product_id IN ({placeholders}) ORDER BY sort_order, id",
                    product_ids,
                ).fetchall()
                for p in pkg_rows:
                    pid = p["product_id"]
                    if pid not in pkg_map:
                        pkg_map[pid] = []
                    pkg_map[pid].append(_package_row_dict(p))
            items = []
            for r in rows:
                item = product_row_dict(r)
                item["packages"] = pkg_map.get(r["id"], [])
                items.append(item)
            handler.send_json({
                "items": items,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total_count + page_size - 1) // page_size),
            })
            return
        pid = int(parts[3])
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        if not row:
            handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        count = conn.execute("SELECT COUNT(*) FROM downloads WHERE product_id = ?", (pid,)).fetchone()[0]
        pkgs = conn.execute(
            "SELECT * FROM product_packages WHERE product_id = ? ORDER BY sort_order, id",
            (pid,),
        ).fetchall()
        out = product_row_dict(row)
        out["download_count"] = count
        out["packages"] = [_package_row_dict(p) for p in pkgs]
        handler.send_json(out)
    except (ValueError, IndexError):
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
    finally:
        conn.close()


def handle_admin_versions_get(handler, path: str):
    """GET /api/admin/versions/<product_id>"""
    if not handler.require_auth():
        return
    parts = [p for p in path.split("/") if p]
    if len(parts) < 4:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        product_id = int(parts[3])
    except ValueError:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM product_versions WHERE product_id = ? ORDER BY id DESC LIMIT 300",
            (product_id,),
        ).fetchall()
        items = [
            {
                "id": r["id"],
                "product_id": r["product_id"],
                "name": r["name"],
                "slug": r["slug"],
                "category": r["category"],
                "platforms": _decode_choices(r["platforms"]) if "platforms" in r.keys() else [],
                "architectures": _decode_choices(r["architectures"]) if "architectures" in r.keys() else [],
                "version": r["version"],
                "summary": r["summary"],
                "description": r["description"],
                "changelog": r["changelog"],
                "status": r["status"],
                "file_name": r["file_name"],
                "file_path": r["file_path"],
                "file_size": r["file_size"],
                "file_sha256": r["file_sha256"],
                "published_at": r["published_at"],
                "created_at": r["created_at"],
                "created_by": r["created_by"],
                "source": r["source"],
            }
            for r in rows
        ]
    finally:
        conn.close()
    handler.send_json({"items": items})


def handle_admin_products_create(handler):
    """POST /api/admin/products"""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = sess
    admin_level = max(1, min(3, int(admin.get("admin_level", 1))))
    try:
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
        return
    name = (body.get("name") or "").strip()
    if not name:
        handler.send_json({"error": "name required"}, status=HTTPStatus.BAD_REQUEST)
        return
    slug = slugify(body.get("slug") or name)
    summary = (body.get("summary") or "").strip()
    description = (body.get("description") or "").strip()
    category = (body.get("category") or "").strip()
    try:
        platforms = _normalize_choices(body.get("platforms", []), PLATFORM_OPTIONS, "platforms")
        architectures = _normalize_choices(body.get("architectures", []), ARCHITECTURE_OPTIONS, "architectures")
    except ValueError as exc:
        handler.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        return
    tags = (body.get("tags") or "").strip()
    announcement = (body.get("announcement") or "").strip()
    version = (body.get("version") or "0.1.0").strip()
    changelog = (body.get("changelog") or "").strip()
    status = (body.get("status") or "draft").strip()
    raw_point_cost = body.get("point_download_cost")
    try:
        point_download_cost = None if raw_point_cost in (None, "") else max(0, int(raw_point_cost))
    except (TypeError, ValueError):
        handler.send_json({"error": "invalid point download cost"}, status=HTTPStatus.BAD_REQUEST)
        return
    points_redemption_enabled = 1 if body.get("points_redemption_enabled", True) else 0
    if status not in {"draft", "published"}:
        status = "draft"
    publish_requires_review = False
    if status == "published" and admin_level < 3:
        status = "draft"
        publish_requires_review = True
    now = now_iso()
    published_at = now if status == "published" else None

    conn = get_db()
    try:
        duplicate = conn.execute(
            "SELECT id FROM products WHERE lower(trim(name)) = lower(trim(?)) LIMIT 1",
            (name,),
        ).fetchone()
        if duplicate:
            handler.send_json(
                {"error": f"产品名称“{name}”已存在，请修改名称或编辑已有产品。"},
                status=HTTPStatus.CONFLICT,
            )
            return
        cur = conn.execute(
            """
            INSERT INTO products (slug, name, summary, description, category, platforms, architectures, tags, announcement, version, changelog, status, created_by, created_at, updated_at, published_at, point_download_cost, points_redemption_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (slug, name, summary, description, category, platforms, architectures, tags, announcement, version, changelog, status, admin["username"], now, now, published_at, point_download_cost, points_redemption_enabled),
        )
        conn.commit()
        pid = cur.lastrowid
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    except sqlite3.IntegrityError:
        handler.send_json(
            {"error": "产品链接标识已存在，请修改产品名称或 slug。"},
            status=HTTPStatus.CONFLICT,
        )
        return
    finally:
        conn.close()

    create_product_version_snapshot(pid, admin["username"], "create")
    out = product_row_dict(row)
    out["publish_requires_review"] = publish_requires_review
    handler.send_json(out, status=HTTPStatus.CREATED)


def handle_admin_products_update(handler, path: str):
    """PUT /api/admin/products/<id>"""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = sess
    parts = [p for p in path.split("/") if p]
    if len(parts) < 4:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        pid = int(parts[3])
        body = handler.read_json_body()
    except Exception:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        if not row:
            handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        admin_level = max(1, min(3, int(admin.get("admin_level", 1))))
        if admin_level == 1 and row["created_by"] != admin["username"]:
            handler.send_json({"error": "lv1 can only edit own products"}, status=HTTPStatus.FORBIDDEN)
            return

        # Snapshot before update
        conn.execute(
            """
            INSERT INTO product_versions (
                product_id, name, slug, category, platforms, architectures, tags, announcement, version, summary, description, changelog, status,
                file_name, file_path, file_size, file_sha256, published_at, created_at, created_by, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["name"],
                row["slug"],
                row["category"],
                row["platforms"],
                row["architectures"],
                row["tags"],
                row["announcement"],
                row["version"],
                row["summary"],
                row["description"],
                row["changelog"],
                row["status"],
                row["file_name"],
                row["file_path"],
                row["file_size"],
                row["file_sha256"],
                row["published_at"],
                now_iso(),
                admin["username"],
                "before_update",
            ),
        )

        name = (body.get("name") if body.get("name") is not None else row["name"]).strip()
        if not name:
            handler.send_json({"error": "name required"}, status=HTTPStatus.BAD_REQUEST)
            return
        duplicate = conn.execute(
            "SELECT id FROM products WHERE lower(trim(name)) = lower(trim(?)) AND id != ? LIMIT 1",
            (name, pid),
        ).fetchone()
        if duplicate:
            handler.send_json(
                {"error": f"产品名称“{name}”已存在，请修改名称或编辑已有产品。"},
                status=HTTPStatus.CONFLICT,
            )
            return
        slug = slugify(body.get("slug") if body.get("slug") is not None else row["slug"])
        summary = (body.get("summary") if body.get("summary") is not None else row["summary"]).strip()
        description = (body.get("description") if body.get("description") is not None else row["description"]).strip()
        category = (body.get("category") if body.get("category") is not None else row["category"]).strip()
        try:
            platforms = _normalize_choices(body["platforms"], PLATFORM_OPTIONS, "platforms") if "platforms" in body else row["platforms"]
            architectures = _normalize_choices(body["architectures"], ARCHITECTURE_OPTIONS, "architectures") if "architectures" in body else row["architectures"]
        except ValueError as exc:
            handler.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        tags = (body.get("tags") if body.get("tags") is not None else row["tags"]).strip()
        announcement = (body.get("announcement") if body.get("announcement") is not None else row["announcement"]).strip()
        version = (body.get("version") if body.get("version") is not None else row["version"]).strip()
        changelog = (body.get("changelog") if body.get("changelog") is not None else row["changelog"]).strip()
        status = (body.get("status") if body.get("status") is not None else row["status"]).strip()
        if status not in {"draft", "published"}:
            status = row["status"]
        publish_requires_review = False
        if status == "published" and int(admin.get("admin_level", 1)) < 3:
            status = row["status"] if row["status"] == "published" else "draft"
            publish_requires_review = True
        published_at = row["published_at"]
        if status == "published" and not published_at:
            published_at = now_iso()
        if status == "draft":
            published_at = None
        raw_point_cost = body.get("point_download_cost", row["point_download_cost"])
        try:
            point_download_cost = None if raw_point_cost in (None, "") else max(0, int(raw_point_cost))
        except (TypeError, ValueError):
            handler.send_json({"error": "invalid point download cost"}, status=HTTPStatus.BAD_REQUEST)
            return
        points_redemption_enabled = (
            1 if body.get("points_redemption_enabled", bool(row["points_redemption_enabled"])) else 0
        )

        conn.execute(
            """
            UPDATE products
            SET slug = ?, name = ?, summary = ?, description = ?, category = ?, platforms = ?, architectures = ?, tags = ?, announcement = ?, version = ?, changelog = ?, status = ?, updated_at = ?, published_at = ?, point_download_cost = ?, points_redemption_enabled = ?
            WHERE id = ?
            """,
            (slug, name, summary, description, category, platforms, architectures, tags, announcement, version, changelog, status, now_iso(), published_at, point_download_cost, points_redemption_enabled, pid),
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    except sqlite3.IntegrityError:
        handler.send_json(
            {"error": "产品链接标识已存在，请修改产品名称或 slug。"},
            status=HTTPStatus.CONFLICT,
        )
        return
    finally:
        conn.close()

    out = product_row_dict(new_row)
    out["publish_requires_review"] = publish_requires_review
    handler.send_json(out)


def handle_admin_products_delete(handler, path: str):
    """DELETE /api/admin/products/<id>"""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = sess
    parts = [p for p in path.split("/") if p]
    if len(parts) != 4:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        pid = int(parts[3])
    except ValueError:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    admin_level = max(1, min(3, int(admin.get("admin_level", 1))))

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        if not row:
            handler.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        owner = row["created_by"] or ""
        owner_level = 1
        if owner == ADMIN_USERNAME:
            owner_level = 3
        elif owner:
            ow = conn.execute("SELECT admin_level FROM admin_accounts WHERE username = ?", (owner,)).fetchone()
            owner_level = max(1, min(3, int(ow["admin_level"] or 1))) if ow else 1

        if admin_level < 3 and owner_level >= 3 and owner and owner != admin["username"]:
            pending = conn.execute(
                "SELECT id FROM product_delete_requests WHERE product_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
                (pid,),
            ).fetchone()
            if pending:
                handler.send_json(
                    {"error": "delete request already pending", "request_id": pending["id"]},
                    status=HTTPStatus.CONFLICT,
                )
                return
            cur = conn.execute(
                """
                INSERT INTO product_delete_requests (
                    product_id, product_name, product_slug, requested_by, requester_level,
                    owner_username, reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (row["id"], row["name"] or "", row["slug"] or "", admin["username"], admin_level, owner, "", now_iso()),
            )
            conn.commit()
            handler.send_json({"ok": True, "requires_owner_approval": True, "request_id": cur.lastrowid}, status=HTTPStatus.ACCEPTED)
            return

        file_path = row["file_path"]
        try:
            _delete_product_graph(conn, pid)
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            handler.send_json({"error": "product delete blocked by related records"}, status=HTTPStatus.CONFLICT)
            return
    finally:
        conn.close()

    if file_path:
        target = (BASE_DIR / file_path).resolve()
        if target.exists() and target.is_file():
            try:
                target.unlink()
            except OSError:
                pass
    handler.send_json({"ok": True})


def handle_admin_upload(handler, path: str):
    """POST /api/admin/products/<id>/upload"""
    sess = handler.get_session()
    if not sess:
        handler.send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return
    sess_token, admin_data = sess
    admin_level = max(1, min(3, int(admin_data.get("admin_level", 1))))
    upload_limit = get_effective_upload_limit_bytes(admin_level)

    parts = [p for p in path.split("/") if p]
    if len(parts) != 5 or parts[4] != "upload":
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        pid = int(parts[3])
    except ValueError:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    if content_length <= 0:
        handler.send_json({"error": "empty body"}, status=HTTPStatus.BAD_REQUEST)
        return
    if content_length > upload_limit:
        handler.send_json(
            {"error": f"file too large for lv{admin_level}, max {upload_limit // (1024 * 1024)}MB"},
            status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
        return

    original_header = handler.headers.get("X-Filename", "").strip()
    original = safe_filename(unquote(original_header))
    if not original_header:
        handler.send_json({"error": "X-Filename header required"}, status=HTTPStatus.BAD_REQUEST)
        return
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        handler.send_json({"error": f"unsupported extension: {ext}"}, status=HTTPStatus.BAD_REQUEST)
        return

    # Platform and architecture — required, bound to the code package
    platform = (handler.headers.get("X-Platform") or "").strip()
    architecture = (handler.headers.get("X-Architecture") or "").strip()
    if platform not in PLATFORM_OPTIONS:
        handler.send_json(
            {"error": f"X-Platform required, must be one of: {', '.join(PLATFORM_OPTIONS)}"},
            status=HTTPStatus.BAD_REQUEST,
        )
        return
    if architecture not in ARCHITECTURE_OPTIONS:
        handler.send_json(
            {"error": f"X-Architecture required, must be one of: {', '.join(ARCHITECTURE_OPTIONS)}"},
            status=HTTPStatus.BAD_REQUEST,
        )
        return

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    stored_name = f"p{pid}-{stamp}-{secrets.token_hex(4)}{ext}"
    target = UPLOAD_DIR / stored_name

    sha = hashlib.sha256()
    size = 0
    with target.open("wb") as out:
        remaining = content_length
        while remaining > 0:
            chunk = handler.rfile.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            size += len(chunk)
            if size > upload_limit:
                out.close()
                target.unlink(missing_ok=True)
                handler.send_json(
                    {"error": f"file too large for lv{admin_level}, max {upload_limit // (1024 * 1024)}MB"},
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                return
            sha.update(chunk)
            out.write(chunk)

    rel = str(target.relative_to(BASE_DIR)).replace("\\", "/")

    conn = get_db()
    upload_project_count = 0
    auto_promoted = False
    old_file = None
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        if not row:
            target.unlink(missing_ok=True)
            handler.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if admin_level == 1 and row["created_by"] != admin_data["username"]:
            target.unlink(missing_ok=True)
            handler.send_json({"error": "lv1 can only upload to own products"}, status=HTTPStatus.FORBIDDEN)
            return
        old_file = row["file_path"]
        conn.execute(
            """
            INSERT INTO product_versions (
                product_id, name, slug, category, platforms, architectures, tags, announcement, version, summary, description, changelog, status,
                file_name, file_path, file_size, file_sha256, published_at, created_at, created_by, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["id"], row["name"], row["slug"], row["category"], row["platforms"], row["architectures"], row["tags"], row["announcement"],
             row["version"], row["summary"], row["description"], row["changelog"], row["status"],
             row["file_name"], row["file_path"], row["file_size"], row["file_sha256"],
             row["published_at"], now_iso(), admin_data["username"], "before_upload"),
        )
        # Update products.file_* for backwards compat (also insert into product_packages below)
        conn.execute(
            "UPDATE products SET file_name = ?, file_path = ?, file_size = ?, file_sha256 = ?, updated_at = ? WHERE id = ?",
            (original, rel, size, sha.hexdigest(), now_iso(), pid),
        )
        # Insert code package with platform + architecture
        sort_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM product_packages WHERE product_id = ?", (pid,)
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO product_packages
               (product_id, platform, architecture, file_name, file_path, file_size, file_sha256, sort_order, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, platform, architecture, original, rel, size, sha.hexdigest(), sort_order, now_iso(), now_iso()),
        )
        conn.execute(
            """
            INSERT INTO admin_upload_events (admin_username, product_id, uploaded_at, file_size)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(admin_username, product_id)
            DO UPDATE SET uploaded_at = excluded.uploaded_at, file_size = excluded.file_size
            """,
            (admin_data["username"], pid, now_iso(), size),
        )
        upload_project_count = conn.execute(
            "SELECT COUNT(*) FROM admin_upload_events WHERE admin_username = ?",
            (admin_data["username"],),
        ).fetchone()[0]

        if (
            not bool(admin_data.get("is_super"))
            and admin_level == 1
            and upload_project_count >= LV1_AUTO_PROMOTE_PROJECT_COUNT
        ):
            conn.execute(
                "UPDATE admin_accounts SET admin_level = 2 WHERE username = ? AND admin_level < 2",
                (admin_data["username"],),
            )
            admin_level = 2
            auto_promoted = True
            admin_data["admin_level"] = 2
            # Update session if active
            sess = session_get(sess_token)
            if sess:
                conn.execute(
                    "UPDATE sessions SET admin_level = 2 WHERE token = ?",
                    (sess_token,),
                )

        conn.commit()
        new_row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()

    if old_file and not auto_promoted:
        old_path = (BASE_DIR / old_file).resolve()
        if old_path.exists() and old_path.is_file() and old_path != target:
            try:
                old_path.unlink()
            except OSError:
                pass

    out = product_row_dict(new_row)
    out["adminLevel"] = admin_level
    out["uploadProjectCount"] = upload_project_count
    out["autoPromoteTarget"] = LV1_AUTO_PROMOTE_PROJECT_COUNT
    out["autoPromoted"] = auto_promoted
    handler.send_json(out)


def handle_admin_version_rollback(handler, path: str):
    """POST /api/admin/versions/<id>/rollback"""
    admin = handler.require_level2_auth()
    if not admin:
        return
    parts = [p for p in path.split("/") if p]
    if len(parts) != 5 or parts[4] != "rollback":
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    try:
        version_id = int(parts[3])
    except ValueError:
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return

    admin_level = max(1, min(3, int(admin.get("admin_level", 1))))
    publish_requires_review = False

    conn = get_db()
    try:
        begin_immediate_with_retry(conn)
        snap = conn.execute("SELECT * FROM product_versions WHERE id = ?", (version_id,)).fetchone()
        if not snap:
            conn.rollback()
            handler.send_json({"error": "version not found"}, status=HTTPStatus.NOT_FOUND)
            return
        row = conn.execute("SELECT * FROM products WHERE id = ?", (snap["product_id"],)).fetchone()
        if not row:
            conn.rollback()
            handler.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)
            return
        conn.execute(
            """
            INSERT INTO product_versions (
                product_id, name, slug, category, platforms, architectures, tags, announcement, version, summary, description, changelog, status,
                file_name, file_path, file_size, file_sha256, published_at, created_at, created_by, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["id"], row["name"], row["slug"], row["category"], row["platforms"], row["architectures"], row["tags"], row["announcement"],
             row["version"], row["summary"], row["description"], row["changelog"], row["status"], row["file_name"], row["file_path"], row["file_size"],
             row["file_sha256"], row["published_at"], now_iso(), admin["username"], "before_rollback"),
        )
        target_status = snap["status"]
        target_published_at = snap["published_at"]
        if target_status == "published" and admin_level < 3:
            target_status = "draft"
            target_published_at = None
            publish_requires_review = True
        conn.execute(
            """
            UPDATE products
            SET name = ?, slug = ?, category = ?, platforms = ?, architectures = ?, tags = ?, announcement = ?, version = ?, summary = ?, description = ?, changelog = ?,
                status = ?, file_name = ?, file_path = ?, file_size = ?, file_sha256 = ?,
                published_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (snap["name"], snap["slug"], snap["category"], snap["platforms"], snap["architectures"], snap["tags"], snap["announcement"],
             snap["version"], snap["summary"], snap["description"], snap["changelog"],
             target_status, snap["file_name"], snap["file_path"], snap["file_size"], snap["file_sha256"],
             target_published_at, now_iso(), snap["product_id"]),
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM products WHERE id = ?", (snap["product_id"],)).fetchone()
    except sqlite3.IntegrityError:
        conn.rollback()
        handler.send_json({"error": "rollback conflicts with existing slug"}, status=HTTPStatus.CONFLICT)
        return
    finally:
        conn.close()

    out = product_row_dict(new_row)
    out["publish_requires_review"] = publish_requires_review
    handler.send_json(out)


# ── Shared helpers ──

def product_row_dict(row):
    """Convert a product row to a JSON-safe dict."""
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "summary": row["summary"],
        "description": row["description"],
        "category": row["category"] if "category" in row.keys() else "",
        "platforms": _decode_choices(row["platforms"]) if "platforms" in row.keys() else [],
        "architectures": _decode_choices(row["architectures"]) if "architectures" in row.keys() else [],
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
        "packages": [],
    }


def _package_row_dict(row):
    """Convert a product_packages row to a JSON-safe dict."""
    return {
        "id": row["id"],
        "product_id": row["product_id"],
        "platform": row["platform"] or "",
        "architecture": row["architecture"] or "",
        "file_name": row["file_name"],
        "file_path": row["file_path"],
        "file_size": row["file_size"],
        "file_sha256": row["file_sha256"],
        "sort_order": int(row["sort_order"] or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def handle_admin_packages_get(handler, path: str):
    """GET /api/admin/products/<id>/packages"""
    if not handler.require_auth():
        return
    parts = [p for p in path.split("/") if p]
    try:
        pid = int(parts[3])
    except (IndexError, ValueError):
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    conn = get_db()
    try:
        pkgs = conn.execute(
            "SELECT * FROM product_packages WHERE product_id = ? ORDER BY sort_order, id",
            (pid,),
        ).fetchall()
        product = conn.execute("SELECT created_by FROM products WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    if not product:
        handler.send_json({"error": "product not found"}, status=HTTPStatus.NOT_FOUND)
        return
    handler.send_json({
        "items": [_package_row_dict(p) for p in pkgs],
        "product_id": pid,
        "product_created_by": product["created_by"],
    })


def handle_admin_packages_delete(handler, path: str):
    """DELETE /api/admin/packages/<id>"""
    if not handler.require_auth():
        return
    parts = [p for p in path.split("/") if p]
    try:
        pkg_id = int(parts[3])
    except (IndexError, ValueError):
        handler.send_json({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
        return
    conn = get_db()
    try:
        pkg = conn.execute("SELECT * FROM product_packages WHERE id = ?", (pkg_id,)).fetchone()
        if not pkg:
            handler.send_json({"error": "package not found"}, status=HTTPStatus.NOT_FOUND)
            return
        # Delete the file
        if pkg["file_path"]:
            file_path = (BASE_DIR / pkg["file_path"]).resolve()
            if file_path.exists() and file_path.is_file():
                try:
                    file_path.unlink()
                except OSError:
                    pass
        conn.execute("DELETE FROM product_packages WHERE id = ?", (pkg_id,))
        conn.commit()
    finally:
        conn.close()
    handler.send_json({"ok": True, "deleted_id": pkg_id})


def create_product_version_snapshot(product_id: int, created_by: str, source: str = "snapshot"):
    """Create a version snapshot from the current product state."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            return None
        cur = conn.execute(
            """
            INSERT INTO product_versions (
                product_id, name, slug, category, platforms, architectures, tags, announcement, version, summary, description, changelog, status,
                file_name, file_path, file_size, file_sha256, published_at, created_at, created_by, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["id"], row["name"], row["slug"], row["category"], row["platforms"], row["architectures"], row["tags"], row["announcement"],
             row["version"], row["summary"], row["description"], row["changelog"], row["status"],
             row["file_name"], row["file_path"], row["file_size"], row["file_sha256"],
             row["published_at"], now_iso(), created_by, source),
        )
        conn.commit()
        vid = cur.lastrowid
        return conn.execute("SELECT * FROM product_versions WHERE id = ?", (vid,)).fetchone()
    finally:
        conn.close()
