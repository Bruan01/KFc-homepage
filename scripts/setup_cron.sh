#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# KFlow vibecoding 社区定时任务安装脚本（Linux 服务器用）
#
# 安装内容：
#   1. 每天凌晨 04:30 抓取全网 vibecoding 排行榜
#      （GitHub / Product Hunt / 中文社区，源配置见 .env）
#   2. 每小时重算站内帖子热度分并结算过期加热包
#
# 用法（在服务器上、项目根目录执行一次即可，重复执行幂等）：
#   bash scripts/setup_cron.sh            # 安装/更新
#   bash scripts/setup_cron.sh --remove   # 移除本脚本安装的任务
#
# 说明：只写入带 >>> kflow-vibecoding <<< 标记的块，不动服务器上其他 crontab。
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLOCK_BEGIN="# >>> kflow-vibecoding >>>"
BLOCK_END="# <<< kflow-vibecoding <<<"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

# Python 解释器：优先项目虚拟环境，退回系统 python3
if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  PY="$PROJECT_DIR/.venv/bin/python"
else
  PY="$(command -v python3)"
  echo "提示: 未找到 $PROJECT_DIR/.venv，使用系统 $PY"
fi

CRAWL_CMD="cd $PROJECT_DIR && $PY manage.py crawl_external >> $LOG_DIR/cron.log 2>&1"
HOTSCORE_CMD="cd $PROJECT_DIR && $PY manage.py refresh_hot_scores >> $LOG_DIR/cron.log 2>&1"

# 取出当前 crontab，剔除旧的 kflow 管理块（幂等的关键）
existing="$(crontab -l 2>/dev/null || true)"
cleaned="$(printf '%s\n' "$existing" | awk -v b="$BLOCK_BEGIN" -v e="$BLOCK_END" '
  $0 == b { skip = 1; next }
  $0 == e { skip = 0; next }
  !skip
')"

if [ "${1:-}" = "--remove" ]; then
  printf '%s\n' "$cleaned" | crontab -
  echo "已移除 kflow-vibecoding 定时任务。"
  exit 0
fi

# 重新写入：其余 crontab + 新的 kflow 管理块
{
  printf '%s\n' "$cleaned"
  echo "$BLOCK_BEGIN"
  echo "# 全网 vibecoding 排行榜每日凌晨抓取"
  echo "30 4 * * * $CRAWL_CMD"
  echo "# 站内帖子热度分每小时重算"
  echo "0 * * * * $HOTSCORE_CMD"
  echo "$BLOCK_END"
} | sed '/./!d' | crontab -

echo "═══ kflow-vibecoding 定时任务已安装 ═══"
crontab -l | sed -n "/$BLOCK_BEGIN/,/$BLOCK_END/p"
echo
echo "日志: $LOG_DIR/cron.log"
echo "确认抓取正常: tail -f $LOG_DIR/cron.log"
