"""
Database backup utilities.
"""
import os
import sqlite3
import time
from pathlib import Path

from app.config import DATA_DIR, DB_BACKUP_INTERVAL_SECONDS, DB_BACKUP_PATHS, DB_PATH


def choose_backup_target() -> Path:
    """Pick the oldest or first-available backup slot (round-robin)."""
    existing = []
    for idx, path in enumerate(DB_BACKUP_PATHS):
        if path.exists():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0
            existing.append((idx, mtime))
        else:
            return path
    existing.sort(key=lambda item: item[1])
    return DB_BACKUP_PATHS[existing[0][0]]


def get_latest_backup_mtime() -> float:
    """Return mtime of the most recent backup file."""
    latest_mtime = 0.0
    for path in DB_BACKUP_PATHS:
        if not path.exists():
            continue
        try:
            latest_mtime = max(latest_mtime, path.stat().st_mtime)
        except OSError:
            continue
    return latest_mtime


def should_run_db_backup(now_ts: float | None = None) -> bool:
    """Check whether it's time to run a backup."""
    if DB_BACKUP_INTERVAL_SECONDS <= 0:
        return False
    if now_ts is None:
        now_ts = time.time()
    latest_mtime = get_latest_backup_mtime()
    if latest_mtime <= 0:
        return True
    return now_ts - latest_mtime >= DB_BACKUP_INTERVAL_SECONDS


def backup_database_once() -> Path | None:
    """Create a SQLite backup to the chosen target path."""
    if not DB_PATH.exists():
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = choose_backup_target()
    temp_target = target.with_suffix(target.suffix + ".tmp")

    src = sqlite3.connect(DB_PATH, timeout=30.0)
    dst = sqlite3.connect(temp_target, timeout=30.0)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()

    os.replace(temp_target, target)
    return target
