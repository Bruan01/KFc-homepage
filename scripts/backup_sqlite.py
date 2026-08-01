#!/usr/bin/env python3
"""Create a consistent SQLite backup, including pages currently in WAL."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"backup destination already exists: {destination}")
    source_db = sqlite3.connect(source)
    target_db = sqlite3.connect(destination)
    try:
        source_db.backup(target_db)
        result = target_db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"backup integrity check failed: {result}")
    finally:
        target_db.close()
        source_db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"source database not found: {args.source}")
    backup(args.source, args.destination)
    print(f"SQLite backup created: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
