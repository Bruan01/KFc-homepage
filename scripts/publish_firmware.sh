#!/usr/bin/env bash
# 发布一版固件：编译 → 签名 → 放进分发目录。
#
# 只做这三件事，不碰 git、不碰服务器——推代码和传 bin 是两件需要人确认的事，
# 脚本代劳只会掩盖"我到底推了什么"。
#
# 存在的理由：v0.10.0 起 bin 少了同名 .sig 就不会被清单收录。手工发布时
# 最容易漏的恰恰是那个 97 字节的小文件，而症状是「有更新但永远升不了」，
# 看起来像网络问题。把它变成一条命令，就没有漏的机会。
#
# 用法：
#   scripts/publish_firmware.sh              # 完整：编译 + 签名 + 核对
#   scripts/publish_firmware.sh --sign-only  # 只给已存在的 bin 重新签名
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CLI="${ARDUINO_CLI:-/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli}"
FQBN="${FQBN:-esp32:esp32:esp32s3:CDCOnBoot=cdc,PartitionScheme=no_fs,PSRAM=opi,FlashSize=16M}"
BUILD_DIR="${BUILD_DIR:-/tmp/ota_build}"
DIST="$ROOT/uploads/firmware"
PY="${PYTHON:-$ROOT/.venv/bin/python}"

SIGN_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --sign-only) SIGN_ONLY=1 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

# 版本号只有一个来源：config.h 里的 FIRMWARE_VERSION。
# 不从 git tag 或参数取，是因为固件里烧的、清单里说的、文件名写的必须
# 是同一个数——三处各写一次就有机会不一致。
VERSION="$(sed -n 's/^#define FIRMWARE_VERSION "\(.*\)"/\1/p' firmware/kflow_terminal/config.h | tr -d '\r')"
if [ -z "$VERSION" ]; then
  echo "读不到 FIRMWARE_VERSION（firmware/kflow_terminal/config.h）" >&2
  exit 1
fi

TARGET="$DIST/kflow_terminal-$VERSION.bin"

if [ "$SIGN_ONLY" -eq 0 ]; then
  echo "== 编译 fw=$VERSION"
  [ -x "$CLI" ] || { echo "找不到 arduino-cli: $CLI" >&2; exit 1; }
  "$CLI" compile --fqbn "$FQBN" --output-dir "$BUILD_DIR" firmware/kflow_terminal
  mkdir -p "$DIST"
  cp "$BUILD_DIR/kflow_terminal.ino.bin" "$TARGET"
fi

[ -f "$TARGET" ] || { echo "没有可签的 bin: $TARGET" >&2; exit 1; }

echo "== 签名"
"$PY" scripts/sign_firmware.py sign "$TARGET"

echo "== 核对（签名脚本自己再验一遍，走的是和板子同一套数学）"
"$PY" scripts/sign_firmware.py verify "$TARGET"

echo
echo "== 完成"
ls -l "$TARGET" "$(dirname "$TARGET")/kflow_terminal-$VERSION.sig"
cat <<EOF

下一步（两件都必须做，缺一样清单就会拒绝这一版）：
  1. 把 bin 和 .sig **一起**传到服务器的 uploads/firmware/
       scp "$TARGET" "$DIST/kflow_terminal-$VERSION.sig" <user>@<host>:<项目路径>/uploads/firmware/
  2. 服务端代码若没更新过，先 git pull + ./redeploy.sh（清单要带 sig 字段）

然后板子串口发 o 立刻升级；能验签通过才会切分区。
EOF
