#!/usr/bin/env bash
# KFlow 一键重新部署脚本（包含 Cloudflare Tunnel 重启）
# - 可选拉取最新代码
# - 安装依赖、检查配置、备份数据库并执行迁移
# - 停止本项目旧进程
# - 使用 setsid 脱离终端，在后台启动 Web 服务和显影 worker
# - 重启 Cloudflare Tunnel
# - 默认监听 0.0.0.0，使服务可通过服务器网卡/反向代理访问
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${RUNTIME_DIR:-/tmp/kflow-homepage}"
SERVER_LOG="${SERVER_LOG:-${RUNTIME_DIR}/server.log}"
WORKER_LOG="${WORKER_LOG:-${RUNTIME_DIR}/imaging-worker.log}"
SERVER_PID_FILE="${SERVER_PID_FILE:-${RUNTIME_DIR}/server.pid}"
WORKER_PID_FILE="${WORKER_PID_FILE:-${RUNTIME_DIR}/imaging-worker.pid}"
LOCK_FILE="${LOCK_FILE:-${RUNTIME_DIR}/redeploy.lock}"
BIND_HOST="${HOST:-0.0.0.0}"
WORKER_INTERVAL="${WORKER_INTERVAL:-2}"
START_TIMEOUT="${START_TIMEOUT:-20}"
PULL_LATEST=0

usage() {
  cat <<'USAGE'
用法：
  ./redeploy-with-tunnel.sh             使用当前工作区代码重新部署并重启 CF Tunnel
  ./redeploy-with-tunnel.sh --pull      先执行 git pull --ff-only，再重新部署
  ./redeploy-with-tunnel.sh --help      显示帮助

可选环境变量：
  HOST=0.0.0.0              监听地址，默认 0.0.0.0（允许外部连接）
  PORT=9000                 服务端口；未设置时读取 Django/.env 配置
  PUBLIC_URL=https://域名/  部署后额外执行公网健康检查
  WORKER_INTERVAL=2         显影任务轮询间隔（秒）
  START_TIMEOUT=20          启动健康检查超时（秒）
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --pull) PULL_LATEST=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] 未知参数：$arg" >&2; usage >&2; exit 2 ;;
  esac
done

mkdir -p "$RUNTIME_DIR"
cd "$PROJECT_DIR"

# 防止两个重新部署任务同时操作同一服务。
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[ERROR] 已有重新部署任务正在运行：$LOCK_FILE" >&2
  exit 1
fi

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON="$PROJECT_DIR/.venv/bin/python"
  PIP="$PROJECT_DIR/.venv/bin/pip"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
  PIP="$PYTHON -m pip"
else
  echo "[ERROR] 未找到 Python。" >&2
  exit 1
fi

if [[ ! -f manage.py ]]; then
  echo "[ERROR] $PROJECT_DIR/manage.py 不存在。" >&2
  exit 1
fi

export HOST="$BIND_HOST"
if [[ -z "${PORT:-}" ]]; then
  PORT="$($PYTHON -c 'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kflow.settings"); from django.conf import settings; print(settings.SERVER_PORT)')"
fi
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "[ERROR] 无效端口：$PORT" >&2
  exit 1
fi
export PORT

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

project_pids() {
  local command_pattern="$1"
  local pid cwd args
  while read -r pid; do
    [[ -n "$pid" && "$pid" != "$$" ]] || continue
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    [[ "$cwd" == "$PROJECT_DIR" ]] || continue
    args="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    [[ "$args" == *"$command_pattern"* ]] || continue
    printf '%s\n' "$pid"
  done < <(pgrep -f 'manage\.py' 2>/dev/null || true)
}

stop_group() {
  local label="$1"
  local command_pattern="$2"
  local pid_file="$3"
  local -a pids=()
  local pid

  if [[ -s "$pid_file" ]]; then
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      pids+=("$pid")
    fi
  fi
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    if [[ ! " ${pids[*]:-} " =~ " $pid " ]]; then
      pids+=("$pid")
    fi
  done < <(project_pids "$command_pattern")

  if (( ${#pids[@]} == 0 )); then
    rm -f "$pid_file"
    log "$label：没有旧进程。"
    return
  fi

  log "$label：停止旧进程 ${pids[*]}..."
  kill "${pids[@]}" 2>/dev/null || true
  for ((i=0; i<10; i++)); do
    local alive=0
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then alive=1; fi
    done
    (( alive == 0 )) && break
    sleep 1
  done
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      log "$label：进程 $pid 未正常退出，强制终止。"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
  rm -f "$pid_file"
}

wait_for_pid() {
  local command_pattern="$1"
  local pid_file="$2"
  local pid
  for ((i=0; i<50; i++)); do
    pid="$(project_pids "$command_pattern" | head -n 1 || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      printf '%s\n' "$pid" > "$pid_file"
      return 0
    fi
    sleep 0.1
  done
  return 1
}

restart_cf_tunnel() {
  log "重启 Cloudflare Tunnel..."
  
  # 尝试使用 systemctl
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet cloudflared 2>/dev/null; then
      log "通过 systemctl 重启 cloudflared..."
      systemctl restart cloudflared
    else
      log "cloudflared 未通过 systemctl 管理，尝试直接重启..."
      # 直接重启 cloudflared 进程
      pkill -f 'cloudflared.*tunnel run' 2>/dev/null || true
      sleep 2
      if [[ -x /usr/bin/cloudflared ]]; then
        setsid -f /usr/bin/cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token \
          9>&- >> /tmp/kflow-homepage/cloudflared.log 2>&1 < /dev/null
      fi
    fi
  else
    # 直接重启 cloudflared 进程
    log "重启 cloudflared 进程..."
    pkill -f 'cloudflared.*tunnel run' 2>/dev/null || true
    sleep 2
    if [[ -x /usr/bin/cloudflared ]]; then
      setsid -f /usr/bin/cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token \
        9>&- >> /tmp/kflow-homepage/cloudflared.log 2>&1 < /dev/null
    fi
  fi
  
  # 等待 tunnel 重新连接
  log "等待 Cloudflare Tunnel 重新连接..."
  sleep 5
  
  # 验证 tunnel 状态
  if pgrep -f 'cloudflared.*tunnel run' >/dev/null 2>&1; then
    log "Cloudflare Tunnel 已重新启动"
  else
    log "[WARN] Cloudflare Tunnel 可能未正常启动，请检查日志"
  fi
}

on_error() {
  local status=$?
  echo >&2
  echo "[ERROR] 重新部署失败（退出码 $status）。" >&2
  echo "--- Web 日志：$SERVER_LOG ---" >&2
  tail -n 80 "$SERVER_LOG" 2>/dev/null >&2 || true
  echo "--- Worker 日志：$WORKER_LOG ---" >&2
  tail -n 80 "$WORKER_LOG" 2>/dev/null >&2 || true
  exit "$status"
}
trap on_error ERR

if (( PULL_LATEST == 1 )); then
  log "拉取最新代码（git pull --ff-only）..."
  git pull --ff-only
fi

log "安装/校验 Python 依赖..."
if [[ "$PIP" == *' '* ]]; then
  $PYTHON -m pip install -r requirements.txt
else
  "$PIP" install -r requirements.txt
fi

log "执行 Django 系统检查..."
"$PYTHON" manage.py check

if [[ -f data/homepage.db ]]; then
  BACKUP_PATH="data/homepage.db.backup-django-$(date +%Y%m%d%H%M%S)"
  log "备份数据库到 $BACKUP_PATH..."
  "$PYTHON" manage.py backup_database --destination "$BACKUP_PATH"
fi

log "执行数据库迁移..."
"$PYTHON" manage.py migrate --fake-initial --noinput

# 先停止 worker，再停止 Web，避免部署期间继续领取新任务。
stop_group "显影 worker" "manage.py process_imaging_jobs" "$WORKER_PID_FILE"
stop_group "Web 服务" "manage.py runserver" "$SERVER_PID_FILE"

: > "$SERVER_LOG"
: > "$WORKER_LOG"

log "后台启动显影 worker..."
setsid -f "$PYTHON" manage.py process_imaging_jobs --interval "$WORKER_INTERVAL" \
  9>&- >> "$WORKER_LOG" 2>&1 < /dev/null
wait_for_pid "manage.py process_imaging_jobs" "$WORKER_PID_FILE"

log "后台启动 Web 服务：http://${BIND_HOST}:${PORT} ..."
setsid -f "$PYTHON" manage.py runserver "${BIND_HOST}:${PORT}" --noreload \
  9>&- >> "$SERVER_LOG" 2>&1 < /dev/null
wait_for_pid "manage.py runserver" "$SERVER_PID_FILE"

log "等待本地 HTTP 健康检查..."
LOCAL_URL="http://127.0.0.1:${PORT}/"
healthy=0
for ((i=0; i<START_TIMEOUT; i++)); do
  if curl -fsS --max-time 3 "$LOCAL_URL" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 1
done
if (( healthy == 0 )); then
  echo "[ERROR] 本地健康检查失败：$LOCAL_URL" >&2
  return_code=1
  false
fi

SERVER_PID="$(cat "$SERVER_PID_FILE")"
WORKER_PID="$(cat "$WORKER_PID_FILE")"

log "本地健康检查通过：$LOCAL_URL"

# 重启 Cloudflare Tunnel
restart_cf_tunnel

if [[ -n "${PUBLIC_URL:-}" ]]; then
  log "检查公网地址：$PUBLIC_URL"
  curl -fsS --max-time 15 "$PUBLIC_URL" >/dev/null
  log "公网健康检查通过：$PUBLIC_URL"
else
  log "未设置 PUBLIC_URL，跳过公网 HTTP 检查。"
fi

trap - ERR
cat <<DONE

========================================
 KFlow 重新部署成功
 Web PID:       $SERVER_PID
 Worker PID:    $WORKER_PID
 监听地址:      ${BIND_HOST}:${PORT}
 本地检查:      $LOCAL_URL
 Web 日志:      $SERVER_LOG
 Worker 日志:   $WORKER_LOG
 Cloudflare Tunnel: 已重启
----------------------------------------
 查看日志:
   tail -f "$SERVER_LOG"
   tail -f "$WORKER_LOG"
   tail -f /tmp/kflow-homepage/cloudflared.log
 再次部署:
   ./redeploy-with-tunnel.sh --pull
========================================
DONE
