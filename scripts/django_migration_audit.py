#!/usr/bin/env python3
"""Read-only audit for a KFlow SQLite database before/after Django migration."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

LEGACY_TABLES = (
    "sessions",
    "products",
    "product_packages",
    "product_versions",
    "downloads",
    "download_requests",
    "users",
    "point_accounts",
    "point_ledger",
    "user_daily_activity",
    "download_entitlements",
    "email_verification_codes",
    "admin_accounts",
    "admin_register_tokens",
    "admin_upload_events",
    "publish_requests",
    "publish_request_votes",
    "product_delete_requests",
    "subscribers",
    "user_subscriptions",
    "system_settings",
)


def audit(database: Path) -> dict:
    uri = f"file:{database.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        available = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = sorted(set(LEGACY_TABLES) - available)
        tables = {}
        for table in LEGACY_TABLES:
            if table not in available:
                continue
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            max_id = None
            if "id" in columns:
                max_id = conn.execute(f'SELECT MAX(id) FROM "{table}"').fetchone()[0]
            tables[table] = {"row_count": count, "max_id": max_id, "columns": columns}
        return {
            "database": str(database),
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "missing_tables": missing,
            "extra_tables": sorted(available - set(LEGACY_TABLES)),
            "tables": tables,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/homepage.db"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.database)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if result["integrity"] == "ok" and not result["missing_tables"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
