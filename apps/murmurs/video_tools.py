"""ffmpeg helpers for murmur videos: 720p compression and watermarked downloads.

ffmpeg ships with `imageio-ffmpeg`, so deployments do not need a system install.
Every helper degrades to "keep the original file" when the binary or the input
is unavailable — uploads and downloads must never fail because of transcoding.
"""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_EDGE = 1280
MAX_DURATION_SECONDS = 31
COMPRESS_THRESHOLD_BYTES = 12 * 1024 * 1024
WATERMARK_MARGIN = 24
WATERMARK_FONT_SIZE = 28


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        logger.warning("ffmpeg is unavailable; video compression and watermarking are disabled", exc_info=True)
        return ""


def should_compress(file_size: int, content_type: str, width: int, height: int) -> bool:
    return (
        content_type != "video/mp4"
        or file_size > COMPRESS_THRESHOLD_BYTES
        or max(width, height) > MAX_EDGE
    )


def fitted_size(width: int, height: int, max_edge: int = MAX_EDGE) -> tuple[int, int]:
    if width <= 0 or height <= 0 or max(width, height) <= max_edge:
        return width, height
    ratio = max_edge / max(width, height)
    return max(2, round(width * ratio)), max(2, round(height * ratio))


def _run_ffmpeg(arguments: list[str], timeout: int) -> bool:
    binary = ffmpeg_path()
    if not binary:
        return False
    try:
        completed = subprocess.run(
            [binary, "-hide_banner", "-loglevel", "error", "-y", *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("ffmpeg could not run", exc_info=True)
        return False
    if completed.returncode != 0:
        logger.info("ffmpeg exited with %s: %s", completed.returncode, (completed.stderr or b"")[:400])
        return False
    return True


def compress_video(source: str | Path) -> bytes | None:
    """Re-encode to a web-friendly 720p H.264 MP4 and return its bytes."""
    with tempfile.TemporaryDirectory(prefix="murmur-compress-") as workspace:
        target = Path(workspace) / "out.mp4"
        filters = (
            f"scale=w='min({MAX_EDGE},iw)':h='min({MAX_EDGE},ih)':force_original_aspect_ratio=decrease,"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        )
        ok = _run_ffmpeg(
            [
                "-i", str(source),
                "-vf", filters,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart",
                "-t", str(MAX_DURATION_SECONDS),
                str(target),
            ],
            timeout=120,
        )
        if not ok:
            return None
        try:
            data = target.read_bytes()
        except OSError:
            return None
        return data or None


def _watermark_badge(author: str) -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    name = re.sub(r"[^0-9A-Za-z_.-]", "", author or "") or "creator"
    text = f"KFlow · @{name}"
    try:
        font = ImageFont.load_default(size=WATERMARK_FONT_SIZE)
    except TypeError:
        font = ImageFont.load_default()
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    pad_x, pad_y = 16, 9
    canvas = Image.new("RGBA", (right - left + pad_x * 2, bottom - top + pad_y * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (0, 0, canvas.width - 1, canvas.height - 1), radius=12, fill=(12, 13, 16, 118)
    )
    draw.text((pad_x - left, pad_y - top), text, font=font, fill=(255, 255, 255, 236))
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def write_watermarked_video(source: str | Path, author: str, target: str | Path) -> bool:
    """Overlay a small KFlow + author badge and atomically write the result."""
    badge = _watermark_badge(author)
    if not badge or not ffmpeg_path():
        return False
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="murmur-watermark-") as workspace:
        badge_path = Path(workspace) / "badge.png"
        badge_path.write_bytes(badge)
        output = Path(workspace) / "out.mp4"
        ok = _run_ffmpeg(
            [
                "-i", str(source),
                "-i", str(badge_path),
                "-filter_complex",
                f"[0:v][1:v]overlay=W-w-{WATERMARK_MARGIN}:H-h-{WATERMARK_MARGIN}:format=auto,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
                "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart",
                str(output),
            ],
            timeout=240,
        )
        if not ok:
            return False
        os.replace(output, target)
    return True
