"""Linux production launcher; TLS and HTTP/2 terminate at the reverse proxy."""
import os

bind = f"{os.environ.get('HOST', '127.0.0.1')}:{os.environ.get('PORT', '9000')}"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
worker_class = "gthread"
timeout = 120
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
