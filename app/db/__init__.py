"""
Database connection factory (Factory pattern).
Provides get_db() and transaction helpers.
Uses thread-local connection caching to avoid per-request connection overhead.
"""
import sqlite3
import threading
import time

from app.config import DB_PATH

# Thread-local storage: each thread keeps one reusable connection.
_local = threading.local()


class _ReusableConnection:
    """Wrapper that delegates to a real sqlite3.Connection."""
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def close(self):
        """Close the underlying connection so SQLite locks are released promptly."""
        self._conn.close()

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
    """Get a thread-local cached SQLite connection (reused across calls).

    ``conn.close()`` on the returned object raises AttributeError to prevent
    accidental closing; use release_db() to explicitly release.
    """
    wrapper = getattr(_local, "wrapper", None)
    if wrapper is not None:
        try:
            wrapper.execute("SELECT 1")
            return wrapper
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            try:
                wrapper._conn.close()
            except Exception:
                pass
    raw = _make_connection()
    wrapper = _ReusableConnection(raw)
    _local.wrapper = wrapper
    return wrapper


def release_db():
    """Explicitly release and close the thread-local connection."""
    wrapper = getattr(_local, "wrapper", None)
    if wrapper is not None:
        try:
            wrapper._conn.rollback()
            wrapper._conn.close()
        except Exception:
            pass
        _local.wrapper = None
