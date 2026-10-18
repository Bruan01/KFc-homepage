#!/usr/bin/env bash
# Build the Tailwind + daisyUI CSS bundles.
#
# Uses the standalone Tailwind CSS CLI binary, so Node.js and npm are not
# needed. The binary is cached under tools/ and only downloaded once.
#
# Usage: ./scripts/build-css.sh [--watch]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOOLS_DIR="$ROOT/tools"
CLI="$TOOLS_DIR/tailwindcss"
VERSION="${TAILWIND_VERSION:-v4.3.3}"

detect_target() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os" in
    Darwin)
      case "$arch" in
        arm64) echo "tailwindcss-macos-arm64" ;;
        x86_64) echo "tailwindcss-macos-x64" ;;
        *) echo "unsupported arch: $arch" >&2; return 1 ;;
      esac
      ;;
    Linux)
      case "$arch" in
        x86_64|amd64) echo "tailwindcss-linux-x64" ;;
        aarch64|arm64) echo "tailwindcss-linux-arm64" ;;
        *) echo "unsupported arch: $arch" >&2; return 1 ;;
      esac
      ;;
    *)
      echo "unsupported OS: $os (build on Linux/macOS, commit the output)" >&2
      return 1
      ;;
  esac
}

ensure_cli() {
  if [[ -x "$CLI" ]]; then
    return
  fi
  local target
  target="$(detect_target)"
  local url="https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}/${target}"
  echo "==> 下载 Tailwind CLI (${target} ${VERSION})..."
  mkdir -p "$TOOLS_DIR"
  curl -fsSL --retry 3 --max-time 300 -o "$CLI" "$url"
  chmod +x "$CLI"
  echo "==> 已缓存到 $CLI"
}

build_one() {
  local src="$1" out="$2"
  local raw_before=0 raw_after=0 gz_after=0
  [[ -f "$out" ]] && raw_before="$(wc -c <"$out" | tr -d ' ')"

  "$CLI" -i "$src" -o "$out" ${WATCH_ARG:+"$WATCH_ARG"} --minify

  raw_after="$(wc -c <"$out" | tr -d ' ')"
  gz_after="$(gzip -c "$out" | wc -c | tr -d ' ')"
  printf '    %-28s raw %6s B   gzip %6s B\n' "$(basename "$out")" "$raw_after" "$gz_after"
  if (( raw_before > 0 && raw_before != raw_after )); then
    printf '    %-28s 变更: %+d B\n' "" "$((raw_after - raw_before))"
  fi
}

WATCH_ARG=""
if [[ "${1:-}" == "--watch" ]]; then
  WATCH_ARG="--watch"
fi

ensure_cli

echo "==> 构建 CSS..."
# Output sits directly in static/ because the asset route only matches
# single-segment paths at the site root (see apps/core/urls.py).
# Every page has its own bundle so it only ships the classes it actually uses;
# the findings shared by all of them live in static/src/_shared.css.
build_one "static/src/forum.css" "static/forum.tailwind.css"
build_one "static/src/home.css" "static/home.tailwind.css"

echo "==> 完成。"
