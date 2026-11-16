#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# LRobotcup 具身智能实时抓取链路 —— 完整部署 / 自检脚本
#
# 作用（一条命令完成「部署前配置 + 定时自动启动 + 可靠运行验证」）：
#   1. 生产库写前备份（backup_database，可 --skip-backup 跳过）。
#   2. 幂等写入具身智能信源（seed_lrobotcup_sources，lrc- 前缀 9 条）。
#   3. 幂等创建具身智能社区版块与开山帖（seed_lrobotcup，需小K 官方号）。
#   4. 立即抓一次（fetch_feeds --prune-days 0）：部署后马上有内容，不等下个
#      30 分钟周期；单源失败隔离，不阻断后续步骤。
#   5. 自检验证（verify_lrobotcup_feeds --strict）：信源/抓取/入库/新鲜度
#      逐项断言，任一不通过则脚本退出码非 0（可被 CI / 部署流程判定为失败）。
#   6. 安装/更新定时任务（setup_cron.sh）：fetch_feeds 每 30 分钟 +
#      publish_lrobotcup_weekly 每周一 09:30，Linux 用 crontab、macOS 用 launchd。
#
# 用法（在项目根目录执行，可重复运行，全部幂等）：
#   bash scripts/setup_lrobotcup_feeds.sh                # 配置 + 抓取 + 自检 + 定时
#   bash scripts/setup_lrobotcup_feeds.sh --verify-only  # 只做自检（巡检 / CI）
#   bash scripts/setup_lrobotcup_feeds.sh --no-cron      # 不重装定时任务
#   bash scripts/setup_lrobotcup_feeds.sh --skip-backup  # 已在部署流程备份过时
#   bash scripts/setup_lrobotcup_feeds.sh --remove       # 卸载本链路的定时任务
#
# 被 start.sh / redeploy.sh 调用时传入 --skip-backup（外层已统一备份）。
# ═══════════════════════════════════════════════════════════════════════
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

SKIP_BACKUP=0
VERIFY_ONLY=0
NO_CRON=0
REMOVE=0
for arg in "$@"; do
  case "$arg" in
    --skip-backup) SKIP_BACKUP=1 ;;
    --verify-only) VERIFY_ONLY=1 ;;
    --no-cron)     NO_CRON=1 ;;
    --remove)      REMOVE=1 ;;
    -h|--help)     sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[ERROR] 未知参数：$arg" >&2; exit 2 ;;
  esac
done

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PY="$PROJECT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "[ERROR] 未找到 Python，无法配置抓取任务。" >&2
  exit 1
fi

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

on_error() {
  local status=$?
  echo >&2
  echo "[ERROR] 具身智能抓取链路配置失败（退出码 ${status}）。" >&2
  echo "        可重跑：bash scripts/setup_lrobotcup_feeds.sh" >&2
  exit "$status"
}
trap on_error ERR

# ── 卸载模式 ────────────────────────────────────────────────────────────
if (( REMOVE == 1 )); then
  log "卸载抓取定时任务（整块 kflow-vibecoding cron，含 fetch_feeds / 周报）…"
  if [[ -f "$PROJECT_DIR/scripts/setup_cron.sh" ]]; then
    bash "$PROJECT_DIR/scripts/setup_cron.sh" --remove || true
  fi
  log "已卸载。信源与条目保留在库中，如需清理请手动处理。"
  exit 0
fi

# ── 仅自检模式 ──────────────────────────────────────────────────────────
if (( VERIFY_ONLY == 1 )); then
  log "仅自检模式：验证具身智能抓取链路…"
  "$PY" manage.py verify_lrobotcup_feeds --strict
  exit 0
fi

# ── 1. 备份（生产库写前）─────────────────────────────────────────────────
if (( SKIP_BACKUP == 0 )) && [[ -f "$PROJECT_DIR/data/homepage.db" ]]; then
  BACKUP_PATH="$PROJECT_DIR/data/homepage.db.backup-lrc-$(date +%Y%m%d%H%M%S)"
  log "备份数据库到 $BACKUP_PATH …"
  "$PY" manage.py backup_database --destination "$BACKUP_PATH"
fi

# ── 2. 幂等写入具身智能信源 ──────────────────────────────────────────────
log "配置具身智能信源（seed_lrobotcup_sources）…"
"$PY" manage.py seed_lrobotcup_sources

# ── 3. 幂等创建具身智能社区版块 ──────────────────────────────────────────
log "配置具身智能社区版块（seed_lrobotcup）…"
"$PY" manage.py seed_lrobotcup

# ── 4. 立即抓一次 ────────────────────────────────────────────────────────
# --prune-days 0：跳过旧条目清理，避免部署首次抓取误删历史调研条目。
# 单源失败已被 fetch_feeds 内部隔离；这里失败只告警，不阻断自检与定时任务。
log "立即抓取一次具身智能信源…"
FETCH_LOG="${FETCH_LOG:-/tmp/kflow-vibecoding/fetch-lrobotcup.log}"
mkdir -p "$(dirname "$FETCH_LOG")"
if "$PY" manage.py fetch_feeds --prune-days 0 >>"${FETCH_LOG}" 2>&1; then
  log "首次抓取完成（日志：${FETCH_LOG}）"
else
  log "[WARN] 首次抓取有信源失败（详情见 ${FETCH_LOG}）；单源失败隔离，30 分钟定时任务会自动重试。"
fi

# ── 5. 自检验证 ──────────────────────────────────────────────────────────
log "自检验证抓取链路（verify_lrobotcup_feeds --strict）…"
"$PY" manage.py verify_lrobotcup_feeds --strict

# ── 6. 安装定时任务（定时自动启动）────────────────────────────────────────
if (( NO_CRON == 0 )); then
  if [[ -f "$PROJECT_DIR/scripts/setup_cron.sh" ]] && command -v crontab >/dev/null 2>&1; then
    log "安装/更新抓取定时任务（fetch_feeds 每 30 分钟 + 具身智能周报每周一 09:30）…"
    bash "$PROJECT_DIR/scripts/setup_cron.sh"
  else
    # macOS：setup_cron.sh 内部走 launchd，不依赖 crontab 是否存在。
    log "未检测到 crontab，尝试用平台调度器（macOS=launchd / Linux=crontab）安装…"
    bash "$PROJECT_DIR/scripts/setup_cron.sh" 2>/dev/null || \
      log "[WARN] 调度器安装未成功（本地沙箱可能拦截 launchd）；生产 Linux 以 crontab 为准。"
  fi
fi

trap - ERR
log "═══ 具身智能实时抓取链路配置完成 ═══"
