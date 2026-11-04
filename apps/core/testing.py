# pyright: reportMissingImports=false
"""测试辅助函数（文件名刻意不叫 test_* ，避免被测试发现器当成用例）。"""
from __future__ import annotations


def csrf_token(client) -> str:
    """返回一个可用的 CSRF token 值。

    页面 HTML 不再种 ``csrftoken`` cookie —— 那会让 CDN 无法缓存 HTML。
    token 统一从 ``/api/csrf`` 领，和前端 ``csrf.js`` 的行为保持一致。
    """
    client.get("/api/csrf")
    return client.cookies["csrftoken"].value
