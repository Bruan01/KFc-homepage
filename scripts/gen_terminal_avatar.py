#!/usr/bin/env python3
"""生成终端页用的方形头像缩略图。

源图 static/xiaok/welcome-portrait-v1.png 是 1060x1484 的立绘（2 MB），
直接塞进 132px 的卡片里既浪费带宽又会被浏览器强行缩放。这里裁出上半身
的正方形区域，输出 264x264（132 CSS px @2x），供 /terminal 页使用。

用法：
    .venv/bin/python scripts/gen_terminal_avatar.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "static" / "xiaok" / "welcome-portrait-v1.png"
OUT = BASE / "static" / "xiaok" / "desk-portrait-264.webp"

# 目标边长（像素）。页面上按 132 CSS px 显示，2x 屏需要 264。
SIZE = 264

# 裁切框用源图相对坐标，换图后不必改数字：取顶部正方形，
# 正好覆盖头部到腰线（立绘 0.71 的宽高比下这是最自然的构图）。
TOP_RATIO = 0.0


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"源图不存在：{SRC}")

    image = Image.open(SRC)
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    width, height = image.size
    side = min(width, height)
    top = int((height - side) * TOP_RATIO)
    box = (0, top, side, top + side)
    square = image.crop(box)

    # 立绘是透明底：先合成到白底，否则 webp 里半透明边缘会在深色背景上发灰。
    canvas = Image.new("RGB", square.size, (255, 255, 255))
    canvas.paste(square, (0, 0), square)
    thumb = canvas.resize((SIZE, SIZE), Image.LANCZOS)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    thumb.save(OUT, "WEBP", quality=90, method=6)
    print(f"{OUT.relative_to(BASE)}  {SIZE}x{SIZE}  {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
