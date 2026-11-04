# pyright: reportMissingImports=false
"""SQLite 连接调优：每个新连接建立时执行。

journal_mode=WAL 是持久化在数据库文件里的：部署后第一个连接切一次，
之后所有连接（包括未来的）都工作在 WAL 下。写事务改走 WAL 文件，
读请求不再被写入阻塞，也基本消除多 worker 下的 database is locked。

synchronous / cache_size / temp_store 是「每连接」参数，必须每个新连接重设。
"""
import os

from django.db.backends.signals import connection_created


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# 单连接页缓存上限（MB）。注意这是「上限」不是「预分配」：SQLite 按实际命中
# 的页惰性占用，库本身只有几十 MB，用满也不会真吃到这么多。
#
# 为什么不直接给 64：gunicorn 3 worker × 4 thread 峰值有 12 条连接，64MB × 12
# 的最坏情况会吃掉 768MB —— 2G 的机器上还有三个后台 worker 在跑。16MB 足够
# 覆盖一次请求的工作集，需要时用 SQLITE_CACHE_MB 调。
SQLITE_CACHE_MB = max(2, min(64, _env_int("SQLITE_CACHE_MB", 16)))


def tune_sqlite_connection(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    # 连接刚建立、尚未开启事务，此时切 journal_mode 是安全的。
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        # WAL 下 NORMAL 已能保证断电不损坏库（只有最后一次检查点可能回退），
        # 换来明显的写入吞吐提升；FULL 只在极端场景才值得。
        cursor.execute("PRAGMA synchronous=NORMAL")
        # 负数表示 KiB。临时表放内存里，排序/去重不再落到磁盘。
        cursor.execute(f"PRAGMA cache_size=-{SQLITE_CACHE_MB * 1024}")
        cursor.execute("PRAGMA temp_store=MEMORY")


def connect():
    connection_created.connect(tune_sqlite_connection, dispatch_uid="kflow_sqlite_pragmas")
