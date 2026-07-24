import hashlib
import json
import secrets
import shutil
import threading
import time
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import unquote

from app.config import ALLOWED_EXTENSIONS, BASE_DIR, CHUNK_UPLOAD_DIR, CHUNK_UPLOAD_SIZE, CHUNK_UPLOAD_TTL_SECONDS, LV1_AUTO_PROMOTE_PROJECT_COUNT, SESSIONS, UPLOAD_DIR
from app.db import get_db
from app.handlers.admin_products import product_row_dict
from app.utils.helpers import now_iso, safe_filename
from app.utils.upload_limits import get_effective_upload_limit_bytes


SESSIONS_BY_UPLOAD_ID = {}
SESSIONS_LOCK = threading.Lock()


def _session(upload_id, admin):
    with SESSIONS_LOCK:
        value = SESSIONS_BY_UPLOAD_ID.get(upload_id)
        if not value or value['expires'] <= time.time() or value['username'] != admin['username']:
            return None
        value['expires'] = time.time() + CHUNK_UPLOAD_TTL_SECONDS
        return dict(value)


def handle_admin_chunk_upload_create(handler, path):
    login = handler.get_session()
    if not login:
        handler.send_json({'error': 'unauthorized'}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = login
    level = max(1, min(3, int(admin.get('admin_level', 1))))
    parts = [part for part in path.split('/') if part]
    try:
        product_id = int(parts[3])
        body = handler.read_json_body()
        size = int(body.get('size', 0))
    except (IndexError, TypeError, ValueError, json.JSONDecodeError):
        handler.send_json({'error': 'invalid upload session request'}, status=HTTPStatus.BAD_REQUEST)
        return
    original = safe_filename(unquote(str(body.get('filename', '')).strip()))
    if len(parts) != 5 or parts[4] != 'upload-sessions' or not original or Path(original).suffix.lower() not in ALLOWED_EXTENSIONS:
        handler.send_json({'error': 'unsupported package format'}, status=HTTPStatus.BAD_REQUEST)
        return
    if size <= 0:
        handler.send_json({'error': 'file size is required'}, status=HTTPStatus.BAD_REQUEST)
        return
    if size > get_effective_upload_limit_bytes(level):
        handler.send_json({'error': f'file too large for lv{level}'}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return
    conn = get_db()
    try:
        product = conn.execute('SELECT id, created_by FROM products WHERE id = ?', (product_id,)).fetchone()
    finally:
        conn.close()
    if not product:
        handler.send_json({'error': 'product not found'}, status=HTTPStatus.NOT_FOUND)
        return
    if level == 1 and product['created_by'] != admin['username']:
        handler.send_json({'error': 'lv1 can only upload to own products'}, status=HTTPStatus.FORBIDDEN)
        return
    CHUNK_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = secrets.token_hex(16)
    (CHUNK_UPLOAD_DIR / upload_id).mkdir()
    count = (size + CHUNK_UPLOAD_SIZE - 1) // CHUNK_UPLOAD_SIZE
    with SESSIONS_LOCK:
        SESSIONS_BY_UPLOAD_ID[upload_id] = {'product_id': product_id, 'username': admin['username'], 'level': level, 'original': original, 'size': size, 'count': count, 'expires': time.time() + CHUNK_UPLOAD_TTL_SECONDS}
    handler.send_json({'upload_id': upload_id, 'chunk_size': CHUNK_UPLOAD_SIZE, 'chunk_count': count})


def handle_admin_chunk_upload_chunk(handler, path):
    login = handler.get_session()
    if not login:
        handler.send_json({'error': 'unauthorized'}, status=HTTPStatus.UNAUTHORIZED)
        return
    _, admin = login
    parts = [part for part in path.split('/') if part]
    try:
        upload_id, index = parts[3], int(parts[5])
        length = int(handler.headers.get('Content-Length', '0'))
    except (IndexError, ValueError):
        handler.send_json({'error': 'invalid chunk request'}, status=HTTPStatus.BAD_REQUEST)
        return
    data = _session(upload_id, admin)
    if not data:
        handler.send_json({'error': 'upload session not found or expired'}, status=HTTPStatus.NOT_FOUND)
        return
    expected = min(CHUNK_UPLOAD_SIZE, data['size'] - index * CHUNK_UPLOAD_SIZE)
    if len(parts) != 6 or parts[2] != 'upload-sessions' or parts[4] != 'chunks' or index < 0 or index >= data['count'] or length != expected:
        handler.send_json({'error': 'invalid chunk request'}, status=HTTPStatus.BAD_REQUEST)
        return
    target = CHUNK_UPLOAD_DIR / upload_id / f'{index:08d}.part'
    remaining = length
    with target.open('wb') as output:
        while remaining:
            block = handler.rfile.read(min(1024 * 1024, remaining))
            if not block:
                break
            output.write(block)
            remaining -= len(block)
    if remaining:
        target.unlink(missing_ok=True)
        handler.send_json({'error': 'incomplete chunk body'}, status=HTTPStatus.BAD_REQUEST)
        return
    handler.send_json({'ok': True})


def handle_admin_chunk_upload_complete(handler, path):
    login = handler.get_session()
    if not login:
        handler.send_json({'error': 'unauthorized'}, status=HTTPStatus.UNAUTHORIZED)
        return
    token, admin = login
    parts = [part for part in path.split('/') if part]
    upload_id = parts[3] if len(parts) == 5 and parts[2] == 'upload-sessions' and parts[4] == 'complete' else ''
    data = _session(upload_id, admin)
    if not data:
        handler.send_json({'error': 'upload session not found or expired'}, status=HTTPStatus.NOT_FOUND)
        return
    directory = CHUNK_UPLOAD_DIR / upload_id
    if any(not (directory / f'{index:08d}.part').is_file() for index in range(data['count'])):
        handler.send_json({'error': 'upload incomplete'}, status=HTTPStatus.CONFLICT)
        return
    extension = Path(data['original']).suffix.lower()
    product_id = data['product_id']
    stamp = datetime.now().strftime(chr(37) + 'Y%m%d%H%M%S')
    target = UPLOAD_DIR / f'p{product_id}-{stamp}-{secrets.token_hex(4)}{extension}'
    temporary = target.with_suffix(f'{target.suffix}.tmp')
    sha256 = hashlib.sha256()
    total = 0
    try:
        with temporary.open('wb') as output:
            for index in range(data['count']):
                with (directory / f'{index:08d}.part').open('rb') as source:
                    while block := source.read(1024 * 1024):
                        output.write(block)
                        sha256.update(block)
                        total += len(block)
        if total != data['size']:
            temporary.unlink(missing_ok=True)
            handler.send_json({'error': 'merged file size mismatch'}, status=HTTPStatus.CONFLICT)
            return
        conn = get_db()
        try:
            row = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
            if not row:
                handler.send_json({'error': 'product not found'}, status=HTTPStatus.NOT_FOUND)
                return
            if data['level'] == 1 and row['created_by'] != admin['username']:
                handler.send_json({'error': 'lv1 can only upload to own products'}, status=HTTPStatus.FORBIDDEN)
                return
            temporary.replace(target)
            rel = str(target.relative_to(BASE_DIR)).replace('\\', '/')
            conn.execute('UPDATE products SET file_name = ?, file_path = ?, file_size = ?, file_sha256 = ?, updated_at = ? WHERE id = ?', (data['original'], rel, total, sha256.hexdigest(), now_iso(), product_id))
            conn.execute('INSERT INTO admin_upload_events (admin_username, product_id, uploaded_at, file_size) VALUES (?, ?, ?, ?) ON CONFLICT(admin_username, product_id) DO UPDATE SET uploaded_at = excluded.uploaded_at, file_size = excluded.file_size', (admin['username'], product_id, now_iso(), total))
            conn.commit()
            result = product_row_dict(conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone())
        finally:
            conn.close()
    except OSError:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        handler.send_json({'error': 'failed to merge upload chunks'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    finally:
        temporary.unlink(missing_ok=True)
    with SESSIONS_LOCK:
        SESSIONS_BY_UPLOAD_ID.pop(upload_id, None)
    shutil.rmtree(directory, ignore_errors=True)
    result['adminLevel'] = data['level']
    result['autoPromoted'] = False
    handler.send_json(result)
