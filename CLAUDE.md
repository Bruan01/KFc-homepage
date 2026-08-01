# CLAUDE.md

KFlow Homepage runs on Django 5.2 LTS while preserving the existing SQLite database and public API contracts. The Django project lives in `kflow/` with domain apps under `apps/`. The frontend remains static HTML/CSS/JS in `static/`.

## Commands

```bash
# Start Django with a WAL-safe database backup and migrations
./start.sh

# Development server without the background wrapper
.venv/bin/python manage.py runserver 127.0.0.1:9000 --noreload

# Verify schema and run all Django tests
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test

# Maintenance commands
.venv/bin/python manage.py backup_database
.venv/bin/python manage.py cleanup_sessions
.venv/bin/python manage.py cleanup_upload_sessions
.venv/bin/python manage.py audit_legacy_database

# Audit legacy tables without changing the database
.venv/bin/python scripts/django_migration_audit.py --database data/homepage.db
```

The default bind is `127.0.0.1:9000`; `HOST`, `PORT`, and other settings can be overridden with environment variables or `.env`. Production should serve `kflow.wsgi:application` or `kflow.asgi:application` through a process manager.

## Architecture

`manage.py` is the Django CLI entry point. `kflow/settings.py` configures SQLite, sessions, static files, uploads, SMTP, and environment values. `kflow/urls.py` includes the domain URLconfs under `apps/`.

- `apps/accounts/`: users, administrators, legacy password compatibility, sessions, registration and login APIs.
- `apps/catalog/`: public products, pages, product CRUD, packages, versions, direct upload and upload limits.
- `apps/downloads/`: downloads, Range streaming, repeat-download approval and persistent chunk uploads.
- `apps/points/`: points ledger, entitlements, redemption and administrator controls.
- `apps/publishing/`: publish/delete approval workflows and weighted votes.
- `apps/dashboard/`: administrator dashboard metrics and table snapshots.
- `apps/core/`: JSON responses, permissions, legacy-session upgrade, static pages, CSRF bootstrap and health check.

To add an endpoint, implement the view in the owning app and register it in that app's `urls.py`; use Django ORM transactions for writes. Keep legacy table names and API response shapes stable unless the migration contract explicitly changes.

## Data and compatibility

- `data/homepage.db` remains the business database. Existing tables use legacy names and are represented by Django models and migrations.
- Run `scripts/backup_sqlite.py` or `./start.sh` before schema changes. The backup uses SQLite Online Backup API so WAL pages are included.
- `scripts/django_migration_audit.py` is read-only and checks integrity, required tables, row counts and maximum IDs.
- `uploads/` stores release packages and chunk-session files; all paths must resolve beneath the project directory.
- The `user_session` and `admin_session` cookie names remain compatible. `LegacySessionMiddleware` upgrades unexpired legacy sessions into Django sessions.
- `apps/accounts/hashers.py` accepts legacy password formats and upgrades successful logins to Django-compatible hashes.

## Security and conventions

- Django CSRF middleware is enabled. HTML pages receive a CSRF cookie and `/csrf.js` adds `X-CSRFToken` to same-origin writes.
- Keep `DJANGO_SECRET_KEY`, `ADMIN_PASSWORD`, SMTP credentials and production host settings in environment variables; never commit real credentials.
- Only published products are downloadable. Product deletion also removes associated package files.
- Uploads are limited by administrator level and allowed archive extension; chunk completion verifies size and optional SHA-256.
- Use `transaction.atomic()` and conditional updates for points, download entitlements and approval state transitions.
- Timestamps are stored as ISO-8601 text for legacy compatibility.

`./start.sh` is the recommended launcher because it performs a WAL-safe backup and migrations. There is no legacy HTTP server in the runtime tree.
