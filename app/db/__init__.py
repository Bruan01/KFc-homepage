"""
Database connection factory (Factory pattern).

Per-thread cached SQLite connections. Within a single HTTP request (one
thread), every ``get_db()`` returns the same underlying connection so the
handler can call it as many times as it likes without paying reconnection
cost.

``conn.close()`` inside a handler is a *soft release*: it rolls back any
open transaction but keeps the connection alive for reuse in the same
request. The hard close happens in ``AppHandler.finish()`` via
``release_db()`` when the request finishes.
"""
import sqlite3
import threading
import time

from app.config import DB_PATH

# Thread-local storage: each thread keeps one reusable connection.
_local = threading.local()


class _ReusableConnection:
    """Wrapper that delegates to a real sqlite3.Connection.

    ``close()`` is a soft release — rollback the transaction but keep the
    underlying connection open so the next ``get_db()`` in the same thread
    reuses it. Actual disposal happens via ``release_db()``.
    """
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._closed = False

    def close(self):
        """Soft release: rollback any pending transaction, keep connection alive."""
        if self._closed:
            return
        try:
            if self._conn.in_transaction:
                self._conn.rollback()
        except Exception:
            # If rollback itself fails the connection is unusable — hard-close it
            # and drop the thread-local reference so the next get_db rebuilds.
            try:
                self._conn.close()
            except Exception:
                pass
            self._closed = True
            wrapper = getattr(_local, "wrapper", None)
            if wrapper is self:
                _local.wrapper = None

    def _hard_close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._conn.close()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, params=None):
        if params is not None:
            return self._conn.execute(sql, params)
        return self._conn.execute(sql)

    def executemany(self, sql, params):
        return self._conn.executemany(sql, params)

    def executescript(self, sql):
        return self._conn.executescript(sql)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def cursor(self):
        return self._conn.cursor()

    def backup(self, target, **kwargs):
        return self._conn.backup(target, **kwargs)


def _make_connection() -> sqlite3.Connection:
    """Create a fresh SQLite connection with standard pragmas."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_db():
    """Return a thread-local SQLite connection, creating one if needed."""
    wrapper = getattr(_local, "wrapper", None)
    if wrapper is not None and not wrapper._closed:
        try:
            wrapper._conn.execute("SELECT 1")
            return wrapper
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            wrapper._hard_close()
    raw = _make_connection()
    wrapper = _ReusableConnection(raw)
    _local.wrapper = wrapper
    return wrapper


def release_db():
    """Explicitly release and close the thread-local connection."""
    wrapper = getattr(_local, "wrapper", None)
    if wrapper is not None:
        try:
            if not wrapper._closed and wrapper._conn.in_transaction:
                wrapper._conn.rollback()
        except Exception:
            pass
        wrapper._hard_close()
        _local.wrapper = None


def begin_immediate_with_retry(conn: sqlite3.Connection, retries: int = 8, base_delay: float = 0.05) -> None:
    """Start a write transaction, retrying transient SQLite lock contention."""
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            conn.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt >= attempts - 1:
                raise
            time.sleep(base_delay * (2 ** min(attempt, 4)))
