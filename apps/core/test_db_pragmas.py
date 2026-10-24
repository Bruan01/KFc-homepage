# pyright: reportMissingImports=false
"""SQLite 连接 PRAGMA 契约：WAL + synchronous=NORMAL。"""
from django.db import connection
from django.test import TransactionTestCase, SimpleTestCase

from apps.core.db import tune_sqlite_connection


class SqlitePragmaTests(TransactionTestCase):
    """PRAGMA 不能在事务内执行，所以不能用会自动开事务的 TestCase。"""

    def test_pragmas_are_applied_on_sqlite(self):
        tune_sqlite_connection(None, connection)
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            cursor.execute("PRAGMA synchronous")
            synchronous = cursor.fetchone()[0]
        # 测试库在内存里时无法进入 WAL（内存库只有 journal_mode=memory），
        # 但同步级别必须已经降为 NORMAL(1)。
        self.assertIn(mode.lower(), ("wal", "memory"))
        self.assertEqual(synchronous, 1)

class NonSqliteTests(SimpleTestCase):
    def test_non_sqlite_connections_are_ignored(self):
        class Fake:
            vendor = "postgresql"

        tune_sqlite_connection(None, Fake())  # 不应抛异常

    def test_signal_is_wired(self):
        from django.db.backends.signals import connection_created

        receivers = [r[1]() for r in connection_created.receivers]
        self.assertTrue(
            any(getattr(r, "__name__", "") == "tune_sqlite_connection" for r in receivers)
        )
