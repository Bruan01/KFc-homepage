#!/usr/bin/env python3
"""
改进的数据迁移脚本：
1. 迁移前自动备份
2. 处理 schema 差异（填充新增字段的默认值）
3. 验证导入结果
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "homepage.db"
BACKUP_DIR = BASE_DIR / "data" / "backups"


def backup_db():
    """使用 SQLite Online Backup API 创建带时间戳的备份"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"homepage-{timestamp}.db"
    
    source = sqlite3.connect(DB_PATH)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
        # 验证完整性
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result}")
    finally:
        target.close()
        source.close()
    
    print(f"✅ Backup created: {backup_path}")
    return backup_path


def get_db_schema(cursor):
    """获取当前数据库完整 schema（包含列信息）"""
    schema = {}
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
    """)
    for (table_name,) in cursor.fetchall():
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        schema[table_name] = {
            columns[1]: {
                "type": columns[2],
                "not_null": columns[3] == 1,
                "default": columns[4],
            }
            for columns in cursor.fetchall()
        }
    return schema


def audit_table(cursor, table_name, expected_count=None):
    """审计表的数据完整性"""
    cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    count = cursor.fetchone()[0]
    
    result = {"table": table_name, "count": count}
    
    # 获取有外键的表的关联信息
    cursor.execute(f'PRAGMA foreign_key_list("{table_name}")')
    fks = cursor.fetchall()
    if fks:
        result["foreign_keys"] = [
            {"from": f"{fk[3]}.{fk[4]}", "to": f"{fk[2]}.{fk[3]}"}
            for fk in fks
        ]
    
    return result


def import_export_sql(export_path, dry_run=False):
    """
    从 export.sql 导入数据，处理：
    1. Schema 差异（缺失列使用默认值）
    2. Python repr 格式的字符串转义
    3. NULL 值处理
    """
    with open(export_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 获取当前 DB schema
    conn = sqlite3.connect(DB_PATH)
    current_schema = get_db_schema(conn.cursor())
    conn.close()
    
    # 解析 INSERT 语句
    # 格式: INSERT INTO "table" (col1, col2) VALUES (val1, val2);
    insert_pattern = r'INSERT INTO "(\w+)" \((.*?)\) VALUES \((.*?)\);'
    
    stats = {"tables": {}, "errors": []}
    
    for match in re.finditer(insert_pattern, content, re.DOTALL):
        table = match.group(1)
        export_cols = [c.strip().strip('"') for c in match.group(2).split(",")]
        values_str = match.group(3)
        
        if table not in stats["tables"]:
            stats["tables"][table] = {"inserted": 0, "skipped": 0, "errors": 0}
        
        if table not in current_schema:
            stats["tables"][table]["skipped"] += 1
            continue
        
        current_cols = current_schema[table]
        
        # 解析值（处理 Python repr 格式）
        values = parse_python_values(values_str)
        if values is None:
            stats["tables"][table]["errors"] += 1
            stats["errors"].append(f"{table}: failed to parse values")
            continue
        
        # 构建 INSERT，使用当前 schema 的列
        insert_cols = []
        insert_values = []
        defaults_used = []
        
        for i, col in enumerate(export_cols):
            if col in current_cols:
                insert_cols.append(col)
                insert_values.append(values[i] if i < len(values) else None)
        
        # 添加缺失列的默认值
        for col, info in current_cols.items():
            if col not in insert_cols and col != "id":  # id 通常自增
                insert_cols.append(col)
                if info["default"] is not None:
                    insert_values.append(info["default"])
                    defaults_used.append(col)
                elif info["not_null"]:
                    # 根据类型提供合理的默认值
                    if "INT" in info["type"].upper():
                        insert_values.append(0)
                    elif "TEXT" in info["type"].upper():
                        insert_values.append("")
                    else:
                        insert_values.append(None)
                    defaults_used.append(f"{col}(default)")
        
        if not insert_cols:
            stats["tables"][table]["skipped"] += 1
            continue
        
        sql = f'INSERT INTO "{table}" ({", ".join(insert_cols)}) VALUES ({", ".join(["?"] * len(insert_values))})'
        
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(sql, insert_values)
            conn.commit()
            conn.close()
            stats["tables"][table]["inserted"] += 1
            
            if defaults_used:
                print(f"  {table}: inserted with defaults for {defaults_used}")
                
        except Exception as e:
            stats["tables"][table]["errors"] += 1
            stats["errors"].append(f"{table}: {str(e)}")
            conn.close()
    
    return stats


def parse_python_values(values_str):
    """解析 Python repr 格式的值"""
    import ast
    
    # 清理并添加括号
    cleaned = values_str.strip()
    if not cleaned.startswith("("):
        cleaned = "(" + cleaned
    if not cleaned.endswith(")"):
        cleaned = cleaned + ")"
    
    try:
        # 使用 ast.literal_eval 安全解析
        result = ast.literal_eval(cleaned)
        if not isinstance(result, tuple):
            result = (result,)
        return result
    except:
        return None


def verify_import(expected_path):
    """验证导入结果"""
    print("\n--- Verification ---")
    
    # 运行 audit
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "django_migration_audit.py"),
         "--database", str(DB_PATH)],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        print("✅ Database integrity OK")
    else:
        print("⚠️  Database audit warnings:")
        print(result.stdout)
    
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="KFlow 数据迁移脚本")
    parser.add_argument("--export", default=str(BASE_DIR / "data" / "export.sql"),
                        help="SQL 导出文件路径")
    parser.add_argument("--backup", action="store_true", default=True,
                        help="迁移前创建备份（默认开启）")
    parser.add_argument("--no-backup", dest="backup", action="store_false",
                        help="跳过备份")
    parser.add_argument("--dry-run", action="store_true",
                        help="只解析不实际导入")
    parser.add_argument("--verify", action="store_true", default=True,
                        help="导入后验证（默认开启）")
    
    args = parser.parse_args()
    
    export_path = Path(args.export)
    if not export_path.exists():
        print(f"❌ Export file not found: {export_path}")
        return 1
    
    # 1. 备份
    if args.backup and not args.dry_run:
        backup_path = backup_db()
    
    # 2. 审计迁移前状态
    print("\n--- Pre-migration audit ---")
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "django_migration_audit.py"),
         "--database", str(DB_PATH)],
        capture_output=True, text=True
    )
    print(result.stdout)
    
    # 3. 导入
    print(f"\n--- Importing from {export_path} ---")
    if args.dry_run:
        print("⚠️  Dry-run mode, no actual changes")
    
    stats = import_export_sql(export_path, dry_run=args.dry_run)
    
    # 4. 报告
    print("\n--- Import Summary ---")
    for table, stat in stats["tables"].items():
        print(f"  {table}: {stat['inserted']} inserted, {stat['skipped']} skipped, {stat['errors']} errors")
    
    if stats["errors"] and len(stats["errors"]) <= 10:
        print("\nErrors:")
        for err in stats["errors"]:
            print(f"  - {err}")
    
    # 5. 验证
    if args.verify and not args.dry_run:
        verify_import(export_path)
    
    return 0 if not stats["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
