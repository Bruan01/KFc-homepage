"""Small, private gallery previews, cached independently of provider originals."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.conf import settings
from PIL import Image, ImageOps


THUMBNAIL_EDGE = 480


def thumbnail_key(job) -> str:
    source = job.image_sha256 or f"{job.image.name}:{job.updated_at.isoformat()}"
    return hashlib.sha256(f"{job.user_id}:{source}:webp-{THUMBNAIL_EDGE}-v1".encode()).hexdigest()


def open_thumbnail(job):
    # The authenticated view serves this cache; filenames never come from a URL.
    root = Path(settings.MEDIA_ROOT) / "imaging" / "thumbnails"
    target = root / f"{thumbnail_key(job)}.webp"
    try:
        return target.open("rb")
    except FileNotFoundError:
        pass
    root.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with job.image.open("rb") as source, Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            with NamedTemporaryFile(dir=root, suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                image.save(output, format="WEBP", quality=78, method=4)
        # Concurrent requests may create the same preview; publish complete files only.
        try:
            os.replace(temporary, target)
        except PermissionError:
            # Windows cannot replace a preview another response already has open.
            if not target.is_file():
                raise
            temporary.unlink()
        temporary = None
        return target.open("rb")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
