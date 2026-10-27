#!/usr/bin/env python3
"""把小 K 立绘转成 ESP32 可直接 pushImage 的 RGB565 头文件。

用法：
    .venv/bin/python scripts/gen_xiaok_splash.py

输出：firmware/kflow_terminal/xiaok_splash.h
- 240 x 262，RGB565（大端序数值，固件里配合 setSwapBytes(true) 使用）
- 底部 58px 留白给标题文字，由固件绘制，不烘焙进图里
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static" / "xiaok" / "welcome-portrait-v1.png"
TARGET = ROOT / "firmware" / "kflow_terminal" / "xiaok_splash.h"

WIDTH = 240
HEIGHT = 262
# 从原图裁掉底部一部分腿脚，保住头部与上半身在 240x262 的画幅里
CROP_TOP = 30


def to_rgb565(image: Image.Image) -> list[int]:
    pixels = image.load()
    out: list[int] = []
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = pixels[x, y][:3]
            out.append(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return out


def main() -> None:
    raw = Image.open(SOURCE).convert("RGBA")
    # 原图是透明底，直接转 RGB 会把背景压成黑色；先合成到白纸上（与屏幕底色一致）
    source = Image.new("RGB", raw.size, (255, 255, 255))
    source.paste(raw, mask=raw.split()[-1])
    ratio = WIDTH / HEIGHT
    crop_height = min(source.height - CROP_TOP, int(source.width / ratio))
    box = (0, CROP_TOP, source.width, CROP_TOP + crop_height)
    image = source.crop(box).resize((WIDTH, HEIGHT), Image.LANCZOS)

    data = to_rgb565(image)

    lines = [
        "// 由 scripts/gen_xiaok_splash.py 生成，勿手工编辑",
        f"// 源图：{SOURCE.relative_to(ROOT)}",
        f"// 尺寸：{WIDTH}x{HEIGHT} RGB565（{WIDTH * HEIGHT * 2 // 1024} KB flash）",
        "#pragma once",
        "",
        f"#define XIAOK_SPLASH_W {WIDTH}",
        f"#define XIAOK_SPLASH_H {HEIGHT}",
        "",
        f"static const uint16_t xiaok_splash[{WIDTH * HEIGHT}] = {{",
    ]
    chunk: list[str] = []
    for index, value in enumerate(data):
        chunk.append(f"0x{value:04X}")
        if len(chunk) == 12:
            lines.append("  " + ", ".join(chunk) + ",")
            chunk = []
    if chunk:
        lines.append("  " + ", ".join(chunk) + ",")
    lines.append("};")
    lines.append("")

    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {TARGET} ({TARGET.stat().st_size // 1024} KB source, {len(data) * 2 // 1024} KB binary)")


if __name__ == "__main__":
    main()
