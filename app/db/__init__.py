"""
Database connection factory (Factory pattern).
Provides get_db() and transaction helpers.
"""
import sqlite3
import time

from app.config import DB_PATH


def get_db() -> sqlite3.Connection:
    """Create a new SQLite connection with Row factory and pragmas."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def begin_immediate_with_retry(conn: sqlite3.Connection, retries: int = 8, base_delay: float = 0.05) -> None:
    """BEGIN IMMEDIATE with exponential backoff retry for concurrent writers."""
    for attempt in range(max(1, int(retries))):
        try:
            conn.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            if attempt >= retries - 1:
                raise
            sleep_s = base_delay * (2 ** min(attempt, 4))
            time.sleep(sleep_s)
