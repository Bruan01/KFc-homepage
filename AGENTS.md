# AGENTS.md — KFlow Homepage

KFlow Homepage is a Django 5.2 LTS product site + community backend. It serves the public storefront, an admin console, the K 士多 redemption store, a vibecoding community (forum + rankings + learn + gamification + notifications), and an OpenAI-compatible "显影" image-generation pipeline. SQLite is the only database and the existing legacy table names and API shapes must stay stable.

This file complements `README.md` and `CLAUDE.md`. Read those first if they answer your question.

## Layout

- `manage.py` / `kflow/` — Django entry, settings, env loader (`kflow/env.py`), storage helper, root `urls.py` mounting every domain app.
- `apps/` — 14 domain apps, each with its own `urls.py`, `views.py`, `models.py`, `services.py`, `tests.py`, and (where applicable) `migrations/` + `management/commands/`:
  - `core` JSON helpers, permissions, legacy-session upgrade, CSRF bootstrap, health check.
  - `accounts` users, admins, legacy password compatibility, sessions, registration/login APIs.
  - `catalog` published products, packages, versions, admin CRUD, uploads.
  - `downloads` Range streaming, repeat-download approval, chunk uploads.
  - `points` ledger, entitlements, redemption, admin controls.
  - `store` K 士多: digital codes, inventory, idempotent exchange.
  - `publishing` approval workflows and weighted votes.
  - `dashboard` admin metrics + table snapshots.
  - `imaging` "显影" prompts, templates, providers (`providers/openai.py`), storage, worker command.
  - `forum` posts, comments, votes, category moderators (`grow_community_members` cmd).
  - `rankings` 全网/站内榜单 + hot-score recompute + external crawler.
  - `learn` 教程与词条 + `seed_learn`.
  - `gamification` 成就、徽章、关卡 (`seed_achievements`).
  - `notifications` 站内通知.
- `static/` — vanilla HTML/CSS/JS frontend (no build pipeline). Admin lives under `static/admin*.html`. `static/csrf.js` injects `X-CSRFToken` for same-origin writes.
- `uploads/` release packages and chunk-session files. `data/` SQLite (`homepage.db`) + timestamped backups + `imaging-originals/` + `logs/`.
- `scripts/` — `backup_sqlite.py`, `backup_manager.py`, `migrate_data.py`, `db_sync.py`, `django_migration_audit.py`, `setup_cron.sh`.
- `docs/` — `vibecoding-ops.md` (cron + external sources), `forum-improvement-plan-2026-09-15.md`, `superpowers/`.
- `Material/` static brand assets referenced by the frontend.

## Commands

Run everything through `.venv/bin/python manage.py …`. Use `./start.sh` for the recommended launcher (WAL-safe backup → migrate → seed achievements/learn → install crontab → start imaging worker → start `runserver` in the background).

```bash
./start.sh                                                # start everything in background
.venv/bin/python manage.py runserver 127.0.0.1:9000 --noreload
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test
.venv/bin/python manage.py migrate --fake-initial --noinput
.venv/bin/python manage.py backup_database --destination <path>
.venv/bin/python manage.py audit_legacy_database
.venv/bin/python manage.py cleanup_sessions
.venv/bin/python manage.py cleanup_upload_sessions
.venv/bin/python manage.py process_imaging_jobs --interval 2   # long-running worker
.venv/bin/python manage.py process_imaging_jobs --once         # drain queue and exit
.venv/bin/python manage.py seed_achievements
.venv/bin/python manage.py seed_learn
.venv/bin/python manage.py crawl_external [--source github|producthunt|v2ex]
.venv/bin/python manage.py refresh_hot_scores
.venv/bin/python manage.py grow_community_members              # forum fixture/moderator helper
bash scripts/setup_cron.sh [--remove]                          # install/update hourly+daily cron
.venv/bin/python scripts/django_migration_audit.py --database data/homepage.db
./redeploy.sh                                                 # restart in place
./redeploy.sh --pull                                          # git pull + redeploy
```

Production should serve `kflow.wsgi:application` (or `kflow.asgi:application`) under Gunicorn/Uvicorn, plus a long-running `process_imaging_jobs --interval 2` worker. Run `manage.py collectstatic --noinput` before going live; hashed assets land in `.staticfiles/` and should be served by Nginx/CDN with `Cache-Control: public, max-age=31536000, immutable`.

## Architecture rules

- One domain app per concern. New endpoints go in the owning app's `views.py` and are registered in that app's `urls.py`; `kflow/urls.py` only `include()`s app urls.
- Keep legacy table names and JSON response shapes stable unless a migration contract explicitly changes them. `data/homepage.db` is the production database — never delete or rewrite it.
- Use `transaction.atomic()` plus conditional updates for any state that touches points, entitlements, downloads, approval transitions, or stock.
- Timestamps are stored as ISO-8601 text for legacy compatibility. Don't switch fields to native datetimes without coordinating the migration.
- Session cookies are `user_session` (frontend) and `admin_session` (admin). `apps.core.middleware.LegacySessionMiddleware` upgrades legacy sessions in-place — drop it only if you've migrated every client.
- The password hasher is `apps.accounts.hashers.LegacyHexPBKDF2PasswordHasher`. Successful logins transparently upgrade to a Django-compatible hash; don't replace it without confirming no legacy hashes remain.
- Static uploads (`uploads/`) and originals (`data/imaging-originals/`) must resolve beneath the project directory — never trust user-supplied paths.

## Imaging ("显影") pipeline

- Calls an OpenAI-compatible image API configured via `CPA_BASE_URL` and `CPA_API_KEY`. A bare origin is normalized to `/v1`; a path that already includes `/v1` (or a proxy prefix) is preserved.
- Each successful generation costs `image_generation_default_cost` credits (default 10) — adjustable from the admin console.
- Identical (user, prompt, size, quality, format) submissions within `IMAGING_CACHE_DAYS` (default 30) reuse the prior image but still debit the user. Override with `IMAGING_CACHE_DAYS`.
- Generated files are re-encoded to PNG/JPEG/WebP (size-optimised) at the original pixel dimensions.
- Tasks are written to the DB before the worker picks them up. The worker is idempotent on retries and never double-debits. Always keep `process_imaging_jobs` running alongside the web server; closing the browser does not cancel a job.
- Admin "配置检查" only hits `/models` to verify the key — it does not generate images.

## External data + cron (rankings / vibecoding)

- `bash scripts/setup_cron.sh` installs a tagged crontab block (`>>> kflow-vibecoding <<<`); running it again is a no-op. Default schedule: `crawl_external` at 04:30 daily, `refresh_hot_scores` hourly. Cron logs go to `data/logs/cron.log`.
- External sources need `.env` keys: `GITHUB_TOKEN` (optional, improves quota), `PRODUCTHUNT_API_KEY` + `PRODUCTHUNT_API_SECRET` (or `PRODUCTHUNT_TOKEN`), `V2EX_HOT_URL` (defaults to the V2EX hot JSON endpoint). These are NOT shipped with the repo — copy `.env` to the server before redeploying.
- Per-source failures are isolated in `crawl_runs`; the previous successful snapshot stays visible until the source recovers.
- Tunable keys live in `SystemSetting` (admin "系统设置"): `points.forum.*`, `forum.boost.<tier>.{cost,score,hours}`, `forum.hot.{like,reply,view}_weight`, `forum.hot.gravity`.

## Conventions

- Frontend is vanilla HTML/CSS/JS in `static/`. There is **no** bundler, no TypeScript, no test runner for JS. Match the existing code style and naming; `theme.js` is the theme switcher, `header.js` mounts the shared header.
- Pyright is configured at `reportMissingImports=false` (see `kflow/settings.py:1` and `kflow/urls.py:1`). Don't enable strict missing-imports — many Django dynamic imports look missing.
- There is no `ruff`/`black`/`flake8`/`pre-commit` config in the repo. Don't add one without asking.
- Don't commit secrets. `.env` is git-ignored; `.env.example` is the template.
- Stop the previous `runserver` / `process_imaging_jobs` processes before restarting; `./start.sh` warns (via `pgrep`) but doesn't kill them.

## Gotchas

- `data/homepage.db` is live. Always run `manage.py backup_database` (or rely on `start.sh`) before `migrate`. Backups go to `data/homepage.db.backup-django-<timestamp>` and use SQLite's Online Backup API so WAL pages are included.
- `./start.sh` runs `migrate --fake-initial` — when adding a brand-new model, generate the migration with `makemigrations` first or `--fake-initial` will treat the table as already present.
- Legacy schema audits: `scripts/django_migration_audit.py` is read-only; use it before any structural change.
- The imaging worker and web server are independent processes. If the web server restarts, in-flight generations continue. If the worker dies, jobs sit in the DB until you restart it.
- Public exposure requires `ALLOWED_HOSTS` (`.env`) to include the domain/IP, plus `HOST=0.0.0.0` (or your public interface) and an open firewall / reverse proxy port. `redeploy-with-tunnel.sh` is the path of least resistance.
- The `forum` migration set is heavy (`0006_add_category_moderators`, `0007_update_forum_categories`); read `apps/forum/services.py` and the related migrations before editing forum permissions.