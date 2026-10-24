# pyright: reportMissingImports=false
"""SQLite 连接调优：每个新连接建立时执行。

journal_mode=WAL 是持久化在数据库文件里的：部署后第一个连接切一次，
之后所有连接（包括未来的）都工作在 WAL 下。写事务改走 WAL 文件，
读请求不再被写入阻塞，也基本消除多 worker 下的 database is locked。
"""
from django.db.backends.signals import connection_created


def tune_sqlite_connection(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    # 连接刚建立、尚未开启事务，此时切 journal_mode 是安全的。
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        # WAL 下 NORMAL 已能保证断电不损坏库（只有最后一次检查点可能回退），
        # 换来明显的写入吞吐提升；FULL 只在极端场景才值得。
        cursor.execute("PRAGMA synchronous=NORMAL")


def connect():
    connection_created.connect(tune_sqlite_connection, dispatch_uid="kflow_sqlite_pragmas")
