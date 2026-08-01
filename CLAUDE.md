# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

KFlow Homepage is a single-machine product website + admin backend built entirely on the **Python 3 standard library** — there are no third-party dependencies, no framework, no `requirements.txt`. HTTP is served via `http.server.ThreadingHTTPServer`, persistence is SQLite, and the frontend is static HTML/CSS/JS in `static/`.

## Commands

```bash
# Run the server (both entry points route to app.server.run_server)
python -m app
python server.py

# Override defaults via env (or a .env file at repo root — see .env.example)
ADMIN_USERNAME=admin ADMIN_PASSWORD=secret PORT=8088 python -m app

# Run the test suite (stdlib unittest; note tests/ is gitignored)
python -m unittest tests.test_user_auth

# Run a single test
python -m unittest tests.test_user_auth.UserAuthIntegrationTests.test_register_and_all_three_login_methods
```

Default bind is `127.0.0.1`, `PORT` env or `9000`, falling back to `8088 → 8000 → 0` (any free port) if the preferred port is taken. The actual bound port is printed on startup.

## Architecture

**`server.py` is a shim.** The 300KB+ root `server.py` is legacy; its `__main__` block immediately delegates to `app.server.run_server()` and exits. All maintained code lives in the `app/` package. Do not edit `server.py` — work in `app/`.

**Request flow.** `app/server.py:run_server()` initializes the DB, seeds it, starts background worker threads, then serves `AppHandler` (in `app/handlers/base.py`). `AppHandler` is a `BaseHTTPRequestHandler` subclass that owns:
- Routing: `app/routes.py` is the single URL-to-handler map. It registers real handler callables through `app/utils/routes.py`; `do_GET`/`do_POST`/`do_PUT`/`do_DELETE` only parse the path and dispatch. Domain handlers are plain functions taking the handler instance, not methods. Use `path_mode="path"` for handlers that need the parsed path and `path_mode="raw_path"` when query parameters must be preserved.
- Shared infrastructure: JSON helpers, cookie parsing, all session/auth checks, static file serving, and dashboard aggregation.

To add an endpoint: implement the handler function in the relevant `app/handlers/*.py` module, then register its explicit callable once in `app/routes.py`. Keep patterns exact; static GET fallback remains in `AppHandler`.

**Configuration** (`app/config.py`) is a load-once singleton. It reads `.env` at import time via `_load_dotenv` (values use `setdefault`, so real env vars win). Admin credentials, upload limits, SMTP settings, and `DASHBOARD_TABLE_ORDER` live here. Persistent sessions are managed by `app/services/session_store.py`.

**Database** (`app/db/`):
- `__init__.py` — `get_db()` returns a **thread-local, reused** connection (WAL mode, `foreign_keys=ON`, 30s busy timeout). `AppHandler.finish()` calls `release_db()` after every request to roll back and close it. Use `begin_immediate_with_retry(conn)` for write transactions to survive lock contention.
- `schema.py` — `init_db()` runs all `CREATE TABLE IF NOT EXISTS` (idempotent), then applies additive migrations via an `ALTER TABLE ADD COLUMN` loop keyed on `PRAGMA table_info`. This is the migration mechanism: to add a column, add it to both `SCHEMA_SQL` and the migration dict. Never drop/rewrite existing columns.
- `seed.py` — inserts one demo product only when `products` is empty.

**Sessions & auth.** Sessions are in-memory (`config.SESSIONS`), keyed by token, with two cookies: `admin_session` and `user_session`. Login is **unified**: legacy `/api/admin/register` returns HTTP 410, and `/admin/login`/`/admin/register` redirect to `/login`. Users register at `/api/user/register`; supplying a valid one-time admin invite code (`admin_register_tokens`) grants both a user and admin identity in one flow. `base.py` exposes graded guards — `require_user_auth`, `require_auth`, `require_super_auth`, `require_level2_auth`, `require_level3_auth` (admin levels lv1/lv2/lv3). `get_session()` also resolves admin privileges from a `user_session` cookie, so a single unified login reaches both frontend and backend.

**Passwords.** Hashed with `pbkdf2_sha256` (`app/utils/crypto.py`). The `users` table historically stored plaintext; legacy accounts are transparently upgraded to a hash when the user re-registers with the correct original password (see `test_registration_upgrades_legacy_account_without_changing_user_id`).

**Background workers** (daemon threads started in `run_server`): DB backup rotator (`app/db/backup.py`, rotates `homepage.db.backup1/2`) and a 60s expired-session cleanup.


## Layout

- `app/routes.py` — the explicit method/path registry; every API URL maps to a real domain handler callable.
- `app/handlers/` — one module per domain (products, auth, downloads, publish approval, chunked uploads, admin dashboard/settings). Functions here receive the `AppHandler` instance.
- `app/services/` — background workers, SMTP email verification (`email_auth.py`), points ledger, and session persistence.
- `app/utils/` — `routes.py`, `crypto.py`, `helpers.py`, `validators.py`, `sse.py`, `upload_limits.py`.
- `static/` — served by `serve_static`; routes like `/product/:slug` map to `product.html`. `Material/` is served via `/material/` with HTTP Range support.
- `uploads/` — uploaded release packages; `uploads/.chunk-sessions/` holds in-progress chunked uploads.
- `data/homepage.db` — SQLite DB (gitignored, along with backups).
- `scripts/db_sync.py` — exports business tables to SQL for syncing to a remote deployment.

## Conventions

- Timestamps are ISO-8601 UTC via `helpers.now_iso()`; store as TEXT.
- Domain handlers must send exactly one response (`send_json` / `send_error`) and read the body with `read_json_body()`.
- Table identifiers built into SQL strings go through `helpers.quote_ident`; the dashboard masks columns listed in `DASHBOARD_MASKED_COLUMNS`.
- Upload size caps are per admin level (`LV1/LV2/LV3_UPLOAD_SIZE_LIMIT`); allowed archive extensions are in `ALLOWED_EXTENSIONS`.
- Only `published` products are downloadable; deleting a product also deletes its uploaded package file.
