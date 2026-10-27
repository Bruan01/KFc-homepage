#!/usr/bin/env python3
"""从首屏立绘派生"眨眼"用的局部小图，供固件待机动画贴帧。

为什么只做局部：
    整屏 240x262 RGB565 是 122KB，一次重贴约 25ms 且整个屏幕会跟着闪。
    待机眨眼要的是"随时可能眨一下"，只能重贴眼睛那两小块（各 ~1.3KB），
    其余像素一点不动，肉眼看不到接缝。

输出：firmware/kflow_terminal/xiaok_face.h
    xiaok_eye_l_open / xiaok_eye_l_closed
    xiaok_eye_r_open / xiaok_eye_r_closed
每条都带 _X/_Y/_W/_H，固件 pushImage 直接用。
open 帧就是原图那块像素（睁回去时贴它），closed 帧是合成出来的。

用法：
    .venv/bin/python scripts/gen_xiaok_face.py            # 生成头文件
    .venv/bin/python scripts/gen_xiaok_face.py --preview  # 只出对比图，不写头文件
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static" / "xiaok" / "welcome-portrait-v1.png"
TARGET = ROOT / "firmware" / "kflow_terminal" / "xiaok_face.h"
PREVIEW = ROOT / "output" / "xiaok_blink_preview.png"

# 必须与 scripts/gen_xiaok_splash.py 完全一致，否则取到的是另一张图的像素
WIDTH = 240
HEIGHT = 262
CROP_TOP = 30

# 眼睛在原图（240x262）里的位置。框比虹膜略大一圈，好把睫毛一起盖住；
# 又不能大到吃到刘海——边界外的像素会原样保留，一旦框里有发丝，
# 闭合帧就会在发丝中间挖出一个肤色补丁。
EYE_L = (99, 58, 120, 81)
EYE_R = (129, 52, 154, 78)

# 闭合时眼睑线相对眼睛中部的下垂量：中间低、两端高，才是"闭眼"而不是"横杠"
LID_DIP = 4.2
LID_THICKNESS = 1.0


def load_source() -> Image.Image:
    """复刻 gen_xiaok_splash.py 的裁切，保证和固件里的底图逐像素对齐。"""
    raw = Image.open(SOURCE).convert("RGBA")
    canvas = Image.new("RGB", raw.size, (255, 255, 255))
    canvas.paste(raw, mask=raw.split()[-1])
    ratio = WIDTH / HEIGHT
    crop_height = min(canvas.height - CROP_TOP, int(canvas.width / ratio))
    box = (0, CROP_TOP, canvas.width, CROP_TOP + crop_height)
    return canvas.crop(box).resize((WIDTH, HEIGHT), Image.LANCZOS)


def to_rgb565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def skin_color(base: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """从眼睛**框外**取一个肤色参考值。

    早先版本按行取中位数当参考色，结果遇到虹膜占满整行的那几行时，
    参考色直接被染成蓝灰，掩膜就把虹膜判成了"皮肤"，闭眼后留下两片蓝斑。
    参考色必须来自眼睛外面。
    """
    x0, y0, x1, y1 = box
    px = base.load()
    samples = []
    for y in list(range(max(0, y0 - 3), y0)) + list(range(y1, min(base.height, y1 + 3))):
        for x in range(x0, x1):
            r, g, b = px[x, y][:3]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx > 150 and (mx - mn) < 60 and r > b + 8:
                samples.append((r, g, b))
    if not samples:
        return (236, 212, 200)
    samples.sort(key=lambda c: c[0] + c[1] + c[2])
    # 取偏暗的三分位而不是中位数：框外上方常常正好压在额头高光上，
    # 取中位数会把参考色抬到接近纯白，于是眼眶里那块真白反而被判成"皮肤"。
    return samples[len(samples) // 3]

def eye_mask(crop: Image.Image, skin: tuple[int, int, int]) -> Image.Image:
    """找出"该被眼睑盖住"的像素。L 模式，255 = 眼睛。"""
    w, h = crop.size
    px = crop.load()
    sr, sg, sb = skin
    mask = Image.new("L", (w, h), 0)
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            # 四周留 1px 不动：那里可能是发丝或脸缘，改了就露馅
            if x < 1 or y < 1 or x >= w - 1 or y >= h - 1:
                continue
            r, g, b = px[x, y][:3]
            dist = abs(r - sr) + abs(g - sg) + abs(b - sb)
            # 光看"跟肤色差多少"会漏掉虹膜上缘那些偏白的高光，以及睫毛上方
            # 那层淡灰蓝的眼影——它们离肤色近，闭眼后会留一片灰斑。补一条
            # 偏冷判定，把整颗眼球连同眼影一起圈进来。
            cold = b > r + 4 and b > 120
            if dist > 70 or cold:
                mp[x, y] = 255
    # 先闭运算再羽化：闭运算填掉眼球内部那些"太淡没被判成眼睛"的小孔，
    # 外轮廓不变；最早只做膨胀，结果眼睑线被撑成一条粗黑横杠。
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    return mask.filter(ImageFilter.GaussianBlur(0.45))


def lash_color(crop: Image.Image) -> tuple[int, int, int]:
    """从原图里取睫毛最深的那撮色，眼睑线用同色才不会像外星人。"""
    px = crop.load()
    w, h = crop.size
    darkest, best = (64, 52, 58), 999
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            s = r + g + b
            if s < best:
                best, darkest = s, (r, g, b)
    return darkest


def inpaint(px, solid: list[list[bool]], w: int, h: int, rounds: int = 80) -> None:
    """扩散修补：待填像素反复吸收四周已确定的颜色。

    比"按行取中位数"强的地方在于它不引入方向性——按行填会在眼睛上下留下
    一条条横向色带，扩散填出来的是一整块连续的皮肤，看不出补过。

    只吸收"像皮肤"的邻居。第一版不限来源，结果睫毛上方那层浅灰眼影
    被当成皮肤扩散进来，闭眼后额头上多出一块蓝灰色斑。
    """
    def skin_like(x: int, y: int) -> bool:
        r, g, b = px[x, y][:3]
        mx, mn = max(r, g, b), min(r, g, b)
        # 必须偏暖。只判"够亮 + 低饱和"会把额头的纯白高光当成皮肤，
        # 于是闭眼后眼眶里被填成一整片白，真机上看着像翻白眼。
        return mx > 150 and (mx - mn) < 45 and r > b + 8

    for _ in range(rounds):
        updates = []
        for y in range(h):
            for x in range(w):
                if not solid[y][x]:
                    continue
                acc = [0, 0, 0]
                n = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if nx < 0 or ny < 0 or nx >= w or ny >= h:
                            continue
                        if solid[ny][nx] or not skin_like(nx, ny):
                            continue
                        c = px[nx, ny]
                        acc[0] += c[0]
                        acc[1] += c[1]
                        acc[2] += c[2]
                        n += 1
                if n:
                    updates.append((x, y, acc[0] // n, acc[1] // n, acc[2] // n))
        if not updates:
            break
        for x, y, r, g, b in updates:
            px[x, y] = (r, g, b)
            solid[y][x] = False


def closed_eye(crop: Image.Image, skin: tuple[int, int, int]) -> Image.Image:
    """合成闭合帧：眼睛区扩散修补成连续皮肤，中间压一条下垂的睫毛弧。"""
    w, h = crop.size
    src = crop.copy()
    px = src.load()
    mask = eye_mask(crop, skin).load()
    lash = lash_color(crop)

    solid = [[mask[x, y] > 127 for x in range(w)] for y in range(h)]
    inpaint(px, solid, w, h)

    # 眼睑线：横向跟随虹膜范围，纵向中间低两端高。端点必须收细——
    # 等宽画过去会在眼角留下两个方头，放大看像贴了两块黑色胶布。
    for y in range(h):
        for x in range(w):
            if not mask[x, y]:
                continue
            t = abs(x - (w - 1) / 2.0) / max(0.5, (w - 1) / 2.0)
            thick = LID_THICKNESS * (1.0 - 0.75 * t * t)
            lid = h * 0.50 + LID_DIP * (1.0 - (2.0 * x / max(1, w - 1) - 1.0) ** 2)
            d = abs(y - lid)
            if d > thick + 1.0:
                continue
            strength = max(0.0, 1.0 - d / (thick + 1.0))
            r, g, b = px[x, y]
            # 全压睫毛色会像贴了黑胶带，混进肤色让线"长在脸上"
            k = 0.45 + 0.45 * strength
            px[x, y] = (
                round(r * (1 - k) + lash[0] * k),
                round(g * (1 - k) + lash[1] * k),
                round(b * (1 - k) + lash[2] * k),
            )
    return src


def pack(image: Image.Image, name: str, origin: tuple[int, int]) -> list[str]:
    w, h = image.size
    ox, oy = origin
    values = []
    px = image.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            values.append(to_rgb565(r, g, b))
    lines = [
        f"#define XIAOK_{name.upper()}_X {ox}",
        f"#define XIAOK_{name.upper()}_Y {oy}",
        f"#define XIAOK_{name.upper()}_W {w}",
        f"#define XIAOK_{name.upper()}_H {h}",
        f"static const uint16_t xiaok_{name}[{w * h}] = {{",
    ]
    chunk: list[str] = []
    for v in values:
        chunk.append(f"0x{v:04X}")
        if len(chunk) == 12:
            lines.append("  " + ", ".join(chunk) + ",")
            chunk = []
    if chunk:
        lines.append("  " + ", ".join(chunk) + ",")
    lines.append("};")
    lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="只出对比图，不写头文件")
    args = parser.parse_args()

    base = load_source()
    regions = {"eye_l": EYE_L, "eye_r": EYE_R}
    header = [
        "// 由 scripts/gen_xiaok_face.py 生成，勿手工编辑",
        "// 待机眨眼用的局部帧：只覆盖眼睛那一小块，其余像素沿用 xiaok_splash",
        "#pragma once",
        "// clang-format off",
        "",
    ]
    tiles = []
    for name, box in regions.items():
        crop = base.crop(box)
        skin = skin_color(base, box)
        opened = crop.copy()
        closed = closed_eye(crop, skin)
        header += pack(opened, f"{name}_open", (box[0], box[1]))
        header += pack(closed, f"{name}_closed", (box[0], box[1]))
        tiles.append((name, crop, closed))

    header.append("// clang-format on")
    header.append("")
    text = "\n".join(header)

    if args.preview:
        scale = 8
        pad = 12
        total_w = sum(c.width * scale + pad for _, _, c in tiles) + pad
        canvas = Image.new("RGB", (total_w, 2 * (max(c.height for _, _, c in tiles) * scale + pad) + pad), (250, 250, 250))
        for idx, (name, opened, closed) in enumerate(tiles):
            x = pad + idx * (opened.width * scale + pad)
            canvas.paste(opened.resize((opened.width * scale, opened.height * scale), Image.NEAREST), (x, pad))
            canvas.paste(closed.resize((closed.width * scale, closed.height * scale), Image.NEAREST), (x, pad + opened.height * scale + pad))
        canvas.save(PREVIEW)
        # 再把两张贴回整图，看它在脸上到底自不自然
        full = base.copy()
        for name, box in regions.items():
            full.paste(closed_eye(base.crop(box), skin_color(base, box)), (box[0], box[1]))
        face = full.crop((80, 40, 175, 110)).resize((95 * 8, 70 * 8), Image.NEAREST)
        face.save(PREVIEW.with_name("xiaok_blink_face.png"))
        print(f"preview -> {PREVIEW}")
        return

    TARGET.write_text(text, encoding="utf-8")
    kb = TARGET.stat().st_size // 1024
    print(f"wrote {TARGET} ({kb} KB source)")


if __name__ == "__main__":
    main()
