"""
Server entry point — wires everything together and starts the HTTP server.
"""
import os
import threading
import time
from http.server import ThreadingHTTPServer

from app.config import (
    AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS,
    AGNES_CHAT_TASK_WORKER_COUNT,
    AGNES_TASK_REFRESH_INTERVAL_SECONDS,
    CHAT_TOKEN_REFRESH_INTERVAL_SECONDS,
    DB_BACKUP_INTERVAL_SECONDS,
    DB_BACKUP_PATHS,
    SERVER_RUNTIME,
)
from app.db.schema import init_db
from app.db.seed import seed_if_empty
from app.db.backup import should_run_db_backup, backup_database_once
from app.handlers.base import AppHandler
from app.services.chat_worker import run_agnes_chat_task_worker
from app.services.video_worker import run_agnes_task_worker
from app.services.token_worker import refresh_agnes_chat_token_stats_once, run_chat_token_worker
from app.services.backup_worker import run_db_backup_worker


def run_server():
    """Initialize database, start background workers, and serve HTTP."""
    init_db()
    seed_if_empty()
    try:
        refresh_agnes_chat_token_stats_once()
    except Exception as exc:
        print(f"[ChatTokenWorker] initial refresh error: {exc}")
    if should_run_db_backup():
        try:
            target = backup_database_once()
            if target is not None:
                print(f"Initial DB backup saved: {target.name}")
        except Exception as exc:
            print(f"[DBBackup] initial backup error: {exc}")

    host = os.getenv("HOST", "127.0.0.1")
    preferred_port = int(os.getenv("PORT", "9000"))
    candidate_ports = [preferred_port, 8088, 8000, 0]
    candidate_ports = list(dict.fromkeys(candidate_ports))

    server = None
    last_error = None
    for port in candidate_ports:
        try:
            server = ThreadingHTTPServer((host, port), AppHandler)
            break
        except OSError as exc:
            last_error = exc
            winerror = getattr(exc, "winerror", None)
            if winerror not in (10013, 10048):
                raise
            print(f"Port {port} unavailable ({exc}). Trying next port...")

    if server is None:
        raise RuntimeError("Failed to bind server to any candidate port.") from last_error

    # Start background workers
    worker = threading.Thread(target=run_agnes_task_worker, daemon=True, name="agnes-task-worker")
    worker.start()

    chat_workers = []
    for idx in range(max(1, AGNES_CHAT_TASK_WORKER_COUNT)):
        chat_worker = threading.Thread(
            target=run_agnes_chat_task_worker,
            args=(f"chat-{idx + 1}",),
            daemon=True,
            name=f"agnes-chat-task-worker-{idx + 1}",
        )
        chat_worker.start()
        chat_workers.append(chat_worker)

    chat_token_worker = threading.Thread(target=run_chat_token_worker, daemon=True, name="agnes-chat-token-worker")
    chat_token_worker.start()

    backup_worker = threading.Thread(target=run_db_backup_worker, daemon=True, name="db-backup-worker")
    backup_worker.start()

    actual_port = server.server_address[1]
    SERVER_RUNTIME["bound_host"] = host
    SERVER_RUNTIME["bound_port"] = actual_port
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"KFlow homepage running on http://{display_host}:{actual_port}")
    print(f"Agnes task worker started: polling every {AGNES_TASK_REFRESH_INTERVAL_SECONDS}s")
    print(f"Agnes chat task workers started: {len(chat_workers)} threads, polling every {AGNES_CHAT_TASK_POLL_INTERVAL_SECONDS}s")
    print(f"Agnes chat token worker started: every {CHAT_TOKEN_REFRESH_INTERVAL_SECONDS}s")
    if DB_BACKUP_INTERVAL_SECONDS > 0:
        print(f"DB backup worker started: every {DB_BACKUP_INTERVAL_SECONDS}s, rotating {len(DB_BACKUP_PATHS)} copies")
    server.serve_forever()
