"""
Database backup worker — periodic SQLite backup.
"""
import time

from app.config import DB_BACKUP_INTERVAL_SECONDS
from app.db.backup import should_run_db_backup, backup_database_once


def run_db_backup_worker():
    """Background worker loop: run database backup at configured intervals."""
    if DB_BACKUP_INTERVAL_SECONDS <= 0:
        print("DB backup worker disabled: DB_BACKUP_INTERVAL_SECONDS <= 0")
        return
    while True:
        try:
            if should_run_db_backup():
                target = backup_database_once()
                if target is not None:
                    print(f"DB backup saved: {target.name}")
        except Exception as exc:
            print(f"[DBBackup] backup error: {exc}")
        time.sleep(DB_BACKUP_INTERVAL_SECONDS)
