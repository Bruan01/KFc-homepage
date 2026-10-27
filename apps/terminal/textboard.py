"""中文正文 → 1-bit 位图板。

固件里编的字库只有 ASCII，屏幕上想出现中文，只能"服务端画好再传下来"。
另一条路是往 flash 里塞一套中文点阵（300KB 起、还只能覆盖子集），而且
换行、避头尾、超长截断这些排版逻辑一旦写进固件，改一个字就要重烧一次。
这里选了前者：一块 216 宽的窄屏单色位图约 4KB，局域网一次请求就下来了，
排版逻辑全在 Python 里，改完即生效。

板子格式（小端，无压缩）：

    u16 count
    重复 count 次：
      u16 x, y, w, h, stride, color   ← color 是 RGB565
      stride*h 字节                    ← 1 bit/像素，1 = 前景，行按字节对齐

固件按块 tft.drawBitmap(x, y, data, w, h, color)，背景保持纸色不动。
"""
from __future__ import annotations

import re
import struct
from functools import lru_cache

from django.conf import settings
from django.utils import timezone

# 每块 12 字节头。字段顺序与固件 BoardHeader 一一对应，改动必须两边一起改。
HEADER = struct.Struct("<HHHHHH")

COLOR_INK = 0x0000
COLOR_MUTED = 0x8410
COLOR_ACCENT = 0x0320

# 行首不该出现的标点。落到行首就硬塞回上一行（宁可右侧超一点），
# 中文排版里这叫避头尾，屏幕上"。"单独占一行的观感尤其糟。
NO_LINE_START = "，。、；：？！）】》」』”’,.;:?!)]}%"

# 字体按平台顺序试。服务器换机器时不用改代码，只有找不到才需要配
# settings.TERMINAL_CJK_FONT 指一个 .ttc/.otf。
FONT_CANDIDATES = (
    # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    # Linux（Debian/Ubuntu 的 noto-cjk 与文泉驿）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
)

# 屏幕 240 宽，左右各留 12。块宽比这更宽就会被 TFT 截掉，排版算宽度时
# 必须用同一个数，否则会在屏幕右缘出现半截字。
BLOCK_LEFT = 12
BLOCK_WIDTH = 216

# 布局写在这里而不是固件里：改文案、调行距都不用重烧，代价只是每次多
# 一次 HTTP。y 的取值刻意避开页脚（252 以下固件自己画时钟）。
LAYOUT = {
    "murmur": (
        {"key": "label", "x": 12, "y": 44, "w": 216, "h": 20, "size": 13, "gap": 2, "color": COLOR_ACCENT},
        {"key": "meta", "x": 12, "y": 70, "w": 216, "h": 17, "size": 12, "gap": 2, "color": COLOR_MUTED},
        {"key": "body", "x": 12, "y": 92, "w": 216, "h": 150, "size": 15, "gap": 6, "color": COLOR_INK},
    ),
    "topic": (
        {"key": "label", "x": 12, "y": 44, "w": 216, "h": 20, "size": 13, "gap": 2, "color": COLOR_ACCENT},
        {"key": "title", "x": 12, "y": 72, "w": 216, "h": 48, "size": 18, "gap": 6, "color": COLOR_INK},
        {"key": "meta", "x": 12, "y": 126, "w": 216, "h": 17, "size": 12, "gap": 2, "color": COLOR_MUTED},
        {"key": "body", "x": 12, "y": 148, "w": 216, "h": 94, "size": 14, "gap": 4, "color": COLOR_INK},
    ),
}

# 允许的 slot。视图只认这几个，越界的 slot 一律 400。
SLOTS = tuple(LAYOUT)

# emoji 在多数中文字体里没有字形，直接画会出豆腐块或半截字。
# 屏幕上没有彩色，删掉比显示一个奇怪的方块更干净。
_EMOJI_RE = re.compile(
    "[" "\U0001f000-\U0001faff" "\u2190-\u21ff" "\u2600-\u27bf" "\ufe0f" "\u2b00-\u2bff" "]+"
)


def _font_paths():
    custom = getattr(settings, "TERMINAL_CJK_FONT", "") or ""
    paths = ([custom] if custom else []) + list(FONT_CANDIDATES)
    return [p for p in paths if p]


@lru_cache(maxsize=16)
def load_font(size: int):
    """按字号取字体对象；找不到中文字体返回 None（上层据此降级）。"""
    from PIL import ImageFont

    for path in _font_paths():
        try:
            return ImageFont.truetype(path, size, index=0)
        except (OSError, ValueError):
            continue
    return None


def cjk_available() -> bool:
    return load_font(15) is not None


def plain_text(raw: str, limit: int = 600) -> str:
    """把正文压成"能上屏的纯文本"：去标签、去 markdown 记号、压空白。"""
    text = raw or ""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"(?m)^\s{0,3}[#>\-\*\+]\s*", "", text)
    text = re.sub(r"[*_~`|]+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def _tokens(line: str):
    """切成"不许拆开"的最小单位：中文一字一个，西文一个词一个。"""
    buf = ""
    for ch in line:
        if ch.isascii() and (ch.isalnum() or ch in "_-/@.:+#&'"):
            buf += ch
            continue
        if buf:
            yield buf
            buf = ""
        yield ch
    if buf:
        yield buf


def wrap_text(text: str, font, max_width: float) -> list[str]:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        raw_line = raw_line.rstrip()
        if not raw_line:
            lines.append("")
            continue
        line = ""
        for tok in _tokens(raw_line):
            if not line and tok == " ":
                continue
            probe = line + tok
            if font.getlength(probe) <= max_width or not line:
                # 单个 token 就超过整行宽（超长链接/英文词）时硬切，否则会把行撑爆。
                if not line and font.getlength(tok) > max_width:
                    for ch in tok:
                        if font.getlength(line + ch) > max_width and line:
                            lines.append(line)
                            line = ch
                        else:
                            line += ch
                    continue
                line = probe
                continue
            if tok[0] in NO_LINE_START:
                # 避头：标点跟着上一行走，宁可右侧略溢出。
                line = probe
                lines.append(line)
                line = ""
                continue
            lines.append(line.rstrip())
            line = "" if tok == " " else tok
        if line:
            lines.append(line.rstrip())
    return lines


def _clip_with_ellipsis(line: str, font, max_width: float) -> str:
    if font.getlength(line + "…") <= max_width:
        return line + "…"
    while line and font.getlength(line + "…") > max_width:
        line = line[:-1]
    return (line + "…") if line else "…"


def _pack_mask(mask) -> tuple[bytes, int]:
    """PIL 的 L 图 → 1bpp 字节流（1 = 有墨）。"""
    from PIL import Image

    width, height = mask.size
    stride = (width + 7) // 8
    # 先把灰度压成纯二值再转 "1"，避免 Floyd-Steinberg 把字边缘抖成麻点。
    bilevel = mask.point(lambda v: 255 if v < 128 else 0).convert("1", dither=Image.Dither.NONE)
    raw = bilevel.tobytes()
    expected = stride * height
    if len(raw) != expected:  # 理论上不会发生；真发生就补零，别把板子写歪
        raw = raw[:expected].ljust(expected, b"\x00")
    return raw, stride


def render_block(text: str, spec: dict) -> tuple[bytes, int]:
    from PIL import Image, ImageDraw

    width, height = spec["w"], spec["h"]
    font = load_font(spec["size"])
    if font is None:
        return b"", 0

    line_h = spec["size"] + spec["gap"]
    max_lines = max(1, height // line_h)
    lines = wrap_text(text, font, width)
    clipped = len(lines) > max_lines
    lines = lines[:max_lines]
    if clipped and lines:
        lines[-1] = _clip_with_ellipsis(lines[-1], font, width)

    canvas = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(lines):
        # 顶部留 1px：中文字形上缘比 ascent 略高，贴边会削顶。
        draw.text((0, 1 + index * line_h), line, font=font, fill=0)
    return _pack_mask(canvas)


def _ago(moment) -> str:
    """相对时间。屏幕上这一行和正文一起渲染，所以也用中文，不混英文。"""
    if not moment:
        return ""
    seconds = int((timezone.now() - moment).total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    if seconds < 86400 * 7:
        return f"{seconds // 86400} 天前"
    return timezone.localtime(moment).strftime("%m/%d")


def latest_murmur():
    from apps.murmurs.models import Murmur

    return Murmur.objects.filter(is_deleted=False).order_by("-id").first()


def latest_topic():
    from apps.forum.models import ForumTopic

    return ForumTopic.objects.filter(status=ForumTopic.STATUS_OPEN).order_by("-created_at", "-id").first()


def _content_for(slot: str) -> dict | None:
    """取一条内容，折成"每个块要画什么字"的字典。没有内容就返回 None。"""
    if slot == "murmur":
        murmurs = latest_murmur()
        if murmurs is None:
            return None
        body = plain_text(murmurs.content)
        return {
            "label": "碎碎念",
            "meta": f"@{murmurs.author_username} · {_ago(_parse_ts(murmurs.created_at))}",
            "body": body or "(这条没有正文)",
        }
    if slot == "topic":
        topic = latest_topic()
        if topic is None:
            return None
        return {
            "label": "最新帖子",
            "meta": f"@{topic.author_username} · {_ago(topic.created_at)}",
            "title": plain_text(topic.title, limit=120) or "(无标题)",
            "body": plain_text(topic.content) or "(这条没有正文)",
        }
    return None


def _parse_ts(value):
    """Murmur.created_at 是 TextField 存的 ISO 串，帖子那边是真 DateTime。"""
    if not value:
        return None
    if hasattr(value, "year"):
        return value
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def empty_text(slot: str) -> dict:
    return {
        "murmur": {"label": "碎碎念", "meta": "", "body": "还没有人发碎碎念"},
        "topic": {"label": "最新帖子", "meta": "", "title": "最新帖子", "body": "论坛还没有新帖"},
    }[slot]


def build_board(slot: str) -> bytes:
    """组装一整屏的文字块。调用方只在 slot 合法时进来。"""
    content = _content_for(slot)
    if content is None:
        content = empty_text(slot)

    blocks: list[bytes] = []
    for spec in LAYOUT[slot]:
        # 没有内容的块不发（碎碎念没有标题行），固件按 count 循环即可。
        text = content.get(spec["key"])
        if text is None:
            continue
        data, stride = render_block(text, spec)
        if not data:
            continue
        blocks.append(
            HEADER.pack(spec["x"], spec["y"], spec["w"], spec["h"], stride, spec["color"]) + data
        )
    return struct.pack("<H", len(blocks)) + b"".join(blocks)
