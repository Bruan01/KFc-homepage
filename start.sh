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
"$PYTHON" manage.py seed_personality_catalog

echo "同步成就与学习内容..."
"$PYTHON" manage.py seed_achievements
"$PYTHON" manage.py seed_learn
"$PYTHON" manage.py seed_feeds

# 配置具身智能实时抓取链路：seed 信源 + 社区版块、立即抓一次、自检、定时自动启动。
# 外层已备份数据库，故传 --skip-backup 避免重复备份；脚本内部全部幂等。
if [ -f "scripts/setup_lrobotcup_feeds.sh" ]; then
  echo "配置具身智能实时抓取链路..."
  bash scripts/setup_lrobotcup_feeds.sh --skip-backup --no-cron
  # 定时任务统一由下面的 setup_cron.sh 安装（含 fetch_feeds 与具身智能周报）。
else
  echo "[WARN] 未找到 scripts/setup_lrobotcup_feeds.sh，跳过具身智能抓取链路配置。"
fi

if [ -f "scripts/setup_cron.sh" ] && command -v crontab >/dev/null 2>&1; then
  echo "安装/更新榜单与信源抓取定时任务..."
  bash scripts/setup_cron.sh
else
  echo "[WARN] 当前环境没有 crontab，跳过定时任务安装（macOS 可由 launchd 承载）。"
fi

LOG_FILE="/tmp/kfc-server.log"
IMAGING_WORKER_LOG_FILE="/tmp/kfc-imaging-worker.log"
COMMUNITY_AI_LOG_FILE="/tmp/kfc-community-ai.log"
PERSONALITY_LOG_FILE="/tmp/kfc-personality.log"
if pgrep -f "[m]anage.py runserver" &>/dev/null; then
  echo "[WARN] Django server may already be running. Check with: pgrep -af 'manage.py runserver'"
fi

if pgrep -f "[m]anage.py process_imaging_jobs" &>/dev/null; then
  echo "[WARN] 显影 worker 可能已经在运行。检查：pgrep -af 'manage.py process_imaging_jobs'"
  IMAGING_WORKER_PID=""
else
  nohup "$PYTHON" manage.py process_imaging_jobs --interval 2 > "$IMAGING_WORKER_LOG_FILE" 2>&1 &
  IMAGING_WORKER_PID=$!
fi

if pgrep -f "[m]anage.py process_community_ai_jobs" &>/dev/null; then
  echo "[WARN] 小 K AI 回复进程可能已在运行。"
  COMMUNITY_AI_PID=""
else
  nohup "$PYTHON" manage.py process_community_ai_jobs --interval 2 > "$COMMUNITY_AI_LOG_FILE" 2>&1 &
  COMMUNITY_AI_PID=$!
fi

if ! pgrep -f "[m]anage.py process_personality_jobs" &>/dev/null; then
  nohup "$PYTHON" manage.py process_personality_jobs --interval 2 > "$PERSONALITY_LOG_FILE" 2>&1 &
fi

nohup "$PYTHON" manage.py runserver "${HOST}:${PORT}" --noreload > "$LOG_FILE" 2>&1 &
PID=$!

sleep 2
if kill -0 "$PID" 2>/dev/null; then
  echo "========================================"
  echo " KFlow Homepage Django 已后台启动"
  echo " PID:       $PID"
  if [ -n "$IMAGING_WORKER_PID" ]; then
    echo " 显影 worker: $IMAGING_WORKER_PID"
  fi
  echo " 地址:      http://${HOST}:${PORT}"
  if [ -n "$COMMUNITY_AI_PID" ]; then echo " 小 K AI:   $COMMUNITY_AI_PID"; fi
  echo " 小 K 日志: $COMMUNITY_AI_LOG_FILE"
  echo " 日志文件:  $LOG_FILE"
  echo "显影日志:   $IMAGING_WORKER_LOG_FILE"
  echo "----------------------------------------"
  echo " 查看日志:  tail -f $LOG_FILE"
  echo " 停止服务:  kill $PID"
  echo "========================================"
else
  echo "[ERROR] Server failed to start. Check log: $LOG_FILE"
  cat "$LOG_FILE"
  exit 1
fi
