#!/usr/bin/env bash
# KFlow Homepage — Django 后台启动脚本
set -euo pipefail

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON=$(command -v python3)
elif command -v python &>/dev/null; then
  PYTHON=$(command -v python)
else
  echo "[ERROR] Python not found."
  exit 1
fi
if [ ! -f "manage.py" ]; then
  echo "[ERROR] manage.py not found."
  exit 1
fi

# Ask Django to resolve .env and explicit environment variables consistently.
SERVER_HOST=$("$PYTHON" -c 'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kflow.settings"); from django.conf import settings; print(settings.SERVER_HOST)')
SERVER_PORT=$("$PYTHON" -c 'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kflow.settings"); from django.conf import settings; print(settings.SERVER_PORT)')
HOST="${SERVER_HOST}"
PORT="${SERVER_PORT}"
export HOST PORT

if [ -f "data/homepage.db" ]; then
  BACKUP_PATH="data/homepage.db.backup-django-$(date +%Y%m%d%H%M%S)"
  "$PYTHON" manage.py backup_database --destination "$BACKUP_PATH"
  echo "数据库备份：$BACKUP_PATH"
fi

echo "应用 Django migrations..."
"$PYTHON" manage.py migrate --fake-initial --noinput

LOG_FILE="/tmp/kfc-server.log"
if pgrep -f "manage.py runserver" &>/dev/null; then
  echo "[WARN] Django server may already be running. Check with: pgrep -af 'manage.py runserver'"
fi

nohup "$PYTHON" manage.py runserver "${HOST}:${PORT}" --noreload > "$LOG_FILE" 2>&1 &
PID=$!

sleep 2
if kill -0 "$PID" 2>/dev/null; then
  echo "========================================"
  echo " KFlow Homepage Django 已后台启动"
  echo " PID:       $PID"
  echo " 地址:      http://${HOST}:${PORT}"
  echo " 日志文件:  $LOG_FILE"
  echo "----------------------------------------"
  echo " 查看日志:  tail -f $LOG_FILE"
  echo " 停止服务:  kill $PID"
  echo "========================================"
else
  echo "[ERROR] Server failed to start. Check log: $LOG_FILE"
  cat "$LOG_FILE"
  exit 1
fi
