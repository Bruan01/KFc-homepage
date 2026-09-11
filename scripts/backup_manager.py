#!/usr/bin/env python3
"""
数据库备份管理工具：
1. 创建带时间戳的备份
2. 保留策略（默认保留最近 10 个）
3. 验证备份完整性
4. 列出/恢复备份
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "homepage.db"
BACKUP_DIR = BASE_DIR / "data" / "backups"


def create_backup(name=None, verify=True):
    """创建数据库备份"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    if name is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"homepage-{timestamp}.db"
    elif not name.endswith(".db"):
        name = f"{name}.db"
    
    backup_path = BACKUP_DIR / name
    
    # 使用 SQLite Online Backup API
    source = sqlite3.connect(DB_PATH)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    
    if verify:
        # 验证备份完整性
        conn = sqlite3.connect(backup_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        
        if result != "ok":
            backup_path.unlink()
            raise RuntimeError(f"Backup integrity check failed: {result}")
    
    size = backup_path.stat().st_size
    print(f"✅ Backup created: {backup_path} ({size / 1024:.1f} KB)")
    return backup_path


def list_backups():
    """列出所有备份"""
    if not BACKUP_DIR.exists():
        print("No backups found")
        return []
    
    backups = []
    for f in BACKUP_DIR.glob("homepage-*.db"):
        stat = f.stat()
        backups.append({
            "path": f,
            "name": f.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime),
        })
    
    backups.sort(key=lambda x: x["modified"], reverse=True)
    
    print(f"\nBackups in {BACKUP_DIR}:")
    print(f"{'Name':<40} {'Size':>10} {'Modified':>20}")
    print("-" * 72)
    for b in backups:
        modified = b['modified'].strftime('%Y-%m-%d %H:%M:%S')
        print(f"{b['name']:<40} {b['size'] / 1024:>9.1f} KB  {modified:>20}")
    
    return backups


def cleanup_old_backups(keep=10):
    """清理旧备份，保留最近 N 个"""
    backups = list_backups()
    if len(backups) <= keep:
        print(f"\nNo cleanup needed ({len(backups)} <= {keep})")
        return
    
    to_delete = backups[keep:]
    print(f"\n🗑️  Deleting {len(to_delete)} old backups:")
    for b in to_delete:
        b["path"].unlink()
        print(f"  Deleted: {b['name']}")


def restore_backup(name):
    """从备份恢复"""
    backup_path = BACKUP_DIR / name
    if not backup_path.exists():
        # 尝试添加 .db 后缀
        backup_path = BACKUP_DIR / f"{name}.db"
    
    if not backup_path.exists():
        print(f"❌ Backup not found: {name}")
        return False
    
    # 先创建当前数据库的备份
    print("Creating backup of current database before restore...")
    create_backup(name="pre-restore-backup.db")
    
    # 复制备份到目标位置
    shutil.copy2(backup_path, DB_PATH)
    print(f"✅ Restored from: {backup_path}")
    
    return True


def export_to_sql(export_path=None):
    """导出数据为 SQL 文件（使用 db_sync.py）"""
    if export_path is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        export_path = BASE_DIR / "data" / f"export-{timestamp}.sql"
    
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "db_sync.py"), "export",
         "--output", str(export_path)],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        print(f"✅ Exported to: {export_path}")
    else:
        print(f"❌ Export failed: {result.stderr}")
    
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="KFlow 数据库备份管理")
    sub = parser.add_subparsers(dest="command", required=True)
    
    # create 子命令
    create_parser = sub.add_parser("create", help="创建备份")
    create_parser.add_argument("--name", help="备份文件名（不含路径）")
    create_parser.add_argument("--no-verify", dest="verify", action="store_false", default=True,
                               help="跳过验证")
    
    # list 子命令
    sub.add_parser("list", help="列出所有备份")
    
    # cleanup 子命令
    cleanup_parser = sub.add_parser("cleanup", help="清理旧备份")
    cleanup_parser.add_argument("--keep", type=int, default=10,
                               help="保留最近 N 个备份（默认 10）")
    
    # restore 子命令
    restore_parser = sub.add_parser("restore", help="从备份恢复")
    restore_parser.add_argument("name", help="备份文件名")
    
    # export 子命令
    export_parser = sub.add_parser("export", help="导出为 SQL")
    export_parser.add_argument("--output", type=Path, help="输出文件路径")
    
    # migrate 子命令
    migrate_parser = sub.add_parser("migrate", help="执行数据迁移")
    migrate_parser.add_argument("--export", type=Path,
                                default=BASE_DIR / "data" / "export.sql",
                                help="SQL 导出文件路径")
    migrate_parser.add_argument("--dry-run", action="store_true",
                               help="只解析不实际导入")
    migrate_parser.add_argument("--no-backup", dest="backup", action="store_false", default=True,
                               help="跳过备份")
    
    args = parser.parse_args()
    
    if args.command == "create":
        create_backup(name=args.name, verify=args.verify)
    elif args.command == "list":
        list_backups()
    elif args.command == "cleanup":
        cleanup_old_backups(keep=args.keep)
    elif args.command == "restore":
        restore_backup(args.name)
    elif args.command == "export":
        export_to_sql(export_path=args.output)
    elif args.command == "migrate":
        from scripts.migrate_data import main as migrate_main
        sys.exit(migrate_main())
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
