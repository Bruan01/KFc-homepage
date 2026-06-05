#!/usr/bin/env python3
"""
数据库同步工具 — 将本地数据导出为 SQL 并写入远程。

用法：
  python scripts/db_export.py              # 导出本地数据到 data/export.sql
  python scripts/db_export.py --push       # 导出 + git add/commit/push
  python scripts/db_import.py data/export.sql  # 远程服务器导入数据
"""
import argparse
import os
import sqlite3
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "homepage.db")
EXPORT_PATH = os.path.join(BASE_DIR, "data", "export.sql")

# 这些表是"业务数据"——导出它们
EXPORT_TABLES = [
    "products",
    "product_versions",
    "users",
    "downloads",
    "download_requests",
    "admin_accounts",
    "admin_register_tokens",
    "admin_upload_events",
    "publish_requests",
    "publish_request_votes",
    "product_delete_requests",
    "subscribers",
    "user_subscriptions",
    "agnes_api_keys",
    "agnes_video_requests",
    "agnes_video_tasks",
    "agnes_video_usage_events",
    "agnes_chat_sessions",
    "agnes_chat_messages",
    "agnes_chat_tasks",
    "agnes_chat_token_stats",
    "agnes_chat_model_config",
]

# 这些表跳过（运行时自动生成或无关紧要）
SKIP_TABLES = set()


def export_db(output_path: str, tables: list[str] | None = None) -> None:
    """Export selected tables as INSERT statements."""
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    lines = ["-- KFlow DB Export", f"-- Generated: {__import__('datetime').datetime.now()}", ""]

    available = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    target_tables = tables or EXPORT_TABLES
    for table_name in target_tables:
        if table_name not in available or table_name in SKIP_TABLES:
            continue

        rows = conn.execute(f"SELECT * FROM \"{table_name}\"").fetchall()
        if not rows:
            continue

        lines.append(f"-- {table_name}: {len(rows)} rows")
        lines.append(f"DELETE FROM \"{table_name}\";")

        for row in rows:
            cols = ", ".join(f'"{k}"' for k in row.keys())
            vals = ", ".join(
                repr(v) if v is not None else "NULL"
                for v in row
            )
            lines.append(f"INSERT INTO \"{table_name}\" ({cols}) VALUES ({vals});")
        lines.append("")

    conn.close()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅ 已导出 {len([l for l in lines if l.startswith('-- ') and 'rows' in l])} 张表")
    print(f"   到 {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB)")


def import_db(input_path: str) -> None:
    """Import from SQL file."""
    if not os.path.exists(input_path):
        print(f"❌ 文件不存在: {input_path}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    sql = open(input_path, encoding="utf-8").read()
    conn.executescript(sql)
    conn.commit()
    conn.close()
    print(f"✅ 已导入 {input_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KFlow 数据库同步工具")
    sub = parser.add_subparsers(dest="command")

    export_parser = sub.add_parser("export", help="导出数据到 SQL 文件")
    export_parser.add_argument("--output", default=EXPORT_PATH)
    export_parser.add_argument("--push", action="store_true", help="导出后自动 git push")

    import_parser = sub.add_parser("import", help="从 SQL 文件导入数据")
    import_parser.add_argument("input", help="SQL 文件路径")

    args = parser.parse_args()

    if args.command == "export":
        export_db(args.output)
        if args.push:
            os.chdir(BASE_DIR)
            subprocess.run(["git", "add", args.output], check=True)
            subprocess.run(["git", "commit", "-m", "db: sync data export"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("✅ 已推送到远程")
    elif args.command == "import":
        import_db(args.input)
    else:
        parser.print_help()
