#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# KFlow vibecoding 社区定时任务安装脚本
#
# 安装内容：
#   1. 每天 04:30 抓取全网 vibecoding 排行榜
#      （GitHub / Product Hunt / 中文社区，源配置见 .env）
#   2. 每小时重算站内帖子热度分
#   3. 每天 00:05 让社区成员数 +1
#
# 用法（在项目根目录执行一次即可，重复执行幂等）：
#   bash scripts/setup_cron.sh            # 安装/更新
#   bash scripts/setup_cron.sh --remove   # 移除本脚本安装的任务
#
# 平台差异：
#   - Linux 服务器：用 crontab（脚本只写 >>> kflow-vibecoding <<< 块，
#     不会动其他任务）
#   - macOS 本机：用 launchd。launchd 在 sandbox 里跑，HOME 在外置卷
#     （/Volumes/...）上时会触发 TCC I/O 错误，所以 plist 与日志全部放
#     /tmp/kflow-vibecoding/，项目目录只通过 bash -c 的 `cd / && cd ...`
#     进入。重启 / 注销后会丢失，需要重新执行本脚本。
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
BLOCK_BEGIN="# >>> kflow-vibecoding >>>"
BLOCK_END="# <<< kflow-vibecoding <<<"
mkdir -p "$LOG_DIR"

if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  PY="$PROJECT_DIR/.venv/bin/python"
else
  PY="$(command -v python3)"
  echo "提示: 未找到 $PROJECT_DIR/.venv，使用系统 $PY"
fi

# launchd std + 项目侧业务日志都写到 /tmp（macOS TCC 安全）。
# data/logs/cron.log 在 sandbox 里无法写入，仅 Linux 路径使用。
LAUNCHD_DIR="/tmp/kflow-vibecoding"
mkdir -p "$LAUNCHD_DIR"

CRAWL_CMD="cd / && cd $PROJECT_DIR && $PY manage.py crawl_external >> $LAUNCHD_DIR/crawl-external.log 2>&1"
HOTSCORE_CMD="cd / && cd $PROJECT_DIR && $PY manage.py refresh_hot_scores >> $LAUNCHD_DIR/refresh-hot-scores.log 2>&1"
GROW_CMD="cd / && cd $PROJECT_DIR && $PY manage.py grow_community_members >> $LAUNCHD_DIR/grow-community-members.log 2>&1"

# ── Linux: 用 crontab ────────────────────────────────────────────────────
install_cron() {
  local existing cleaned
  existing="$(crontab -l 2>/dev/null || true)"
  cleaned="$(printf '%s\n' "$existing" | awk -v b="$BLOCK_BEGIN" -v e="$BLOCK_END" '
    $0 == b { skip = 1; next }
    $0 == e { skip = 0; next }
    !skip
  ')"
  {
    printf '%s\n' "$cleaned"
    echo "$BLOCK_BEGIN"
    echo "# 全网 vibecoding 排行榜每日凌晨抓取"
    echo "30 4 * * * $CRAWL_CMD"
    echo "# 站内帖子热度分每小时重算"
    echo "0 * * * * $HOTSCORE_CMD"
    echo "# 社区成员数每日 +1（凌晨 00:05 执行）"
    echo "5 0 * * * $GROW_CMD"
    echo "$BLOCK_END"
  } | sed '/./!d' | crontab -
  echo "═══ kflow-vibecoding 定时任务已安装（crontab） ═══"
  crontab -l | sed -n "/$BLOCK_BEGIN/,/$BLOCK_END/p"
}

remove_cron() {
  local existing cleaned
  existing="$(crontab -l 2>/dev/null || true)"
  cleaned="$(printf '%s\n' "$existing" | awk -v b="$BLOCK_BEGIN" -v e="$BLOCK_END" '
    $0 == b { skip = 1; next }
    $0 == e { skip = 0; next }
    !skip
  ')"
  printf '%s\n' "$cleaned" | crontab -
  echo "已移除 kflow-vibecoding 定时任务（crontab）。"
}

# ── macOS: 用 launchd ────────────────────────────────────────────────────
# 关键决定：plist 写到 /tmp/kflow-vibecoding/ 而不是 ~/Library/LaunchAgents/，
# 因为后者在 HOME 位于 /Volumes/... 外置卷时会被 launchd sandbox 拒读
# （Bootstrap failed: 5 Input/output error）。
# 这意味着重启 / 注销后任务会失效，重新执行本脚本即可。
LABEL_PREFIX="com.kflow.vibecoding"

write_plist() {
  local label="$1" desc="$2" hour="$3" minute="$4" cmd="$5"
  local path="$LAUNCHD_DIR/${LABEL_PREFIX}.${label}.plist"
  local cmd_escaped="${cmd//&/&amp;}"
  cat > "$path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL_PREFIX}.${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>${cmd_escaped}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>PATH</key>
        <string>${PROJECT_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${hour}</integer>
        <key>Minute</key>
        <integer>${minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LAUNCHD_DIR}/${label}.log</string>
    <key>StandardErrorPath</key>
    <string>${LAUNCHD_DIR}/${label}.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
  printf '  • %s (%s)\n' "$path" "$desc"
}

install_launchd() {
  echo "═══ kflow-vibecoding 定时任务已安装（launchd） ═══"
  echo "Plist:"
  write_plist "crawl-external"      "全网 vibecoding 排行榜每日 04:30 抓取"  4 30 "$CRAWL_CMD"
  write_plist "refresh-hot-scores"  "站内帖子热度分每小时重算"               0  0 "$HOTSCORE_CMD"
  write_plist "grow-community-members" "社区成员数每日 00:05 +1"            0  5 "$GROW_CMD"
  echo
  for label in crawl-external refresh-hot-scores grow-community-members; do
    launchctl bootout "$LAUNCHD_DIR/${LABEL_PREFIX}.${label}.plist" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_DIR/${LABEL_PREFIX}.${label}.plist" 2>/dev/null || true
    launchctl enable "gui/$(id -u)/${LABEL_PREFIX}.${label}" 2>/dev/null || true
  done
  echo
  echo "已加载："
  launchctl list 2>&1 | grep -i kflow | sed 's/^/  /'
  echo
  echo "日志: $LAUNCHD_DIR/<job>.log"
  echo "确认抓取正常: tail -f $LAUNCHD_DIR/crawl-external.log"
  echo
  echo "⚠️  /tmp 在 macOS 重启后会被清空，重新执行 bash scripts/setup_cron.sh 即可恢复。"
}

remove_launchd() {
  for label in crawl-external refresh-hot-scores grow-community-members; do
    launchctl bootout "gui/$(id -u)/${LABEL_PREFIX}.${label}" 2>/dev/null || true
    rm -f "$LAUNCHD_DIR/${LABEL_PREFIX}.${label}.plist"
  done
  echo "已卸载 launchd 任务并删除 plist。"
}

# ── 分发 ────────────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
  Darwin)
    if [ "${1:-}" = "--remove" ]; then
      remove_launchd
      remove_cron
    else
      install_launchd
      # 同时清掉旧 crontab 块，避免重复触发
      remove_cron 2>/dev/null || true
    fi
    ;;
  Linux|*)
    if [ "${1:-}" = "--remove" ]; then
      remove_cron
    else
      install_cron
    fi
    ;;
esac