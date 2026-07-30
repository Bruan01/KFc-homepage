#!/usr/bin/env bash
# KFlow Homepage — 后台启动脚本
set -euo pipefail

cd "$(dirname "$0")"

# 检查 Python
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
  echo "[ERROR] Python not found."
  exit 1
fi

PYTHON=$(command -v python3 || command -v python)

# 检查 server.py
if [ ! -f "server.py" ]; then
  echo "[ERROR] server.py not found."
  exit 1
fi

# 从 .env 读取端口（如果存在）
if [ -f ".env" ]; then
  PORT_LINE=$(grep -E '^PORT=' .env | head -1)
  if [ -n "$PORT_LINE" ]; then
    PORT_FROM_ENV="${PORT_LINE#PORT=}"
    : "${PORT:=$PORT_FROM_ENV}"
  fi
fi

# 默认值
: "${ADMIN_USERNAME:=admin}"
: "${ADMIN_PASSWORD:=admin123}"
: "${PORT:=9000}"

export ADMIN_USERNAME
export ADMIN_PASSWORD
export PORT

LOG_FILE="/tmp/kfc-server.log"

# 如果已运行则提示
if pgrep -f "python.*-m app" &>/dev/null; then
  echo "[WARN] Server may already be running. Check with: pgrep -af 'python.*-m app'"
fi

# 后台启动
nohup $PYTHON -m app > "$LOG_FILE" 2>&1 &
PID=$!

# 等一会检查是否存活
sleep 2
if kill -0 "$PID" 2>/dev/null; then
  echo "========================================"
  echo " KFlow Homepage 已后台启动"
  echo " PID:       $PID"
  echo " 端口:      $PORT"
  echo " 地址:      http://127.0.0.1:$PORT"
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
