# pyright: reportMissingImports=false
"""Gunicorn 生产配置。

启动方式（redeploy.sh 会自动用这条命令）：

    .venv/bin/python -m gunicorn -c deploy/gunicorn.conf.py kflow.wsgi:application

为什么是 gthread 而不是 sync：这个站几乎全是「读 SQLite + 拼字节」的短请求，
线程模型共享地址空间，内存开销比多进程小，2G 的机器上更划算。GIL 在这里
不是瓶颈——真正耗时的是磁盘和网络，不是 Python 字节码。
"""
import os


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# 默认只监听回环：Caddy 在同一台机器上反代。外面还有 Cloudflare。
# 想直连调试时用 GUNICORN_BIND=0.0.0.0:9000 显式覆盖。
bind = os.getenv("GUNICORN_BIND", "127.0.0.1:9000")

# 2 核机器：3 个进程足够覆盖 CPU，4 个线程吃掉等待 I/O 的空档。
# 12 个并发槽对现在这个量级是过剩的，真要调先看 ab 的 Time per request。
workers = max(1, _env_int("GUNICORN_WORKERS", 3))
threads = max(1, _env_int("GUNICORN_THREADS", 4))
worker_class = "gthread"

timeout = _env_int("GUNICORN_TIMEOUT", 60)
# 必须小于 redeploy.sh 里 stop_group 的 10 秒强杀窗口，否则每次部署都会留残进程。
graceful_timeout = _env_int("GUNICORN_GRACEFUL_TIMEOUT", 8)
keepalive = 5

# 定期回收进程，避免长期运行累积的碎片和小泄漏（社区站有大量长连接与缓存字典）。
max_requests = _env_int("GUNICORN_MAX_REQUESTS", 2000)
max_requests_jitter = 200

# 日志走 stdout/stderr，由 redeploy.sh 重定向到 data 目录外的 runtime 日志。
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
# 不记录健康检查，日志里省掉一半噪音。
access_log_format = '%({x-forwarded-for}i)s "%(r)s" %(s)s %(b)s %(L)ss'

proc_name = "kflow-web"

# 回环 + 本机 Caddy，转发来的 XFF 可以信任。
forwarded_allow_ips = os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")
