"""Small, fixed-host image cache shared by public cast cards and private reports."""
import hashlib
import io
import urllib.request
import uuid

from django.conf import settings
from PIL import Image

from apps.community_ai.provider import _NoRedirect
from .catalog import safe_image


def character_image_bytes(url):
    if not safe_image(url):
        raise ValueError("图片地址不受支持")
    folder = settings.BASE_DIR / "data" / "personality-images"
    target = folder / (hashlib.sha256(url.encode()).hexdigest() + ".webp")
    if target.is_file() and 0 < target.stat().st_size <= 3 * 1024 * 1024:
        return target.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "KFlow-Xinying/2.0"})
    with urllib.request.build_opener(_NoRedirect()).open(req, timeout=10) as response:
        raw = response.read(3 * 1024 * 1024 + 1)
    if len(raw) > 3 * 1024 * 1024:
        raise ValueError("图片过大")
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > 20000000:
            raise ValueError("图片尺寸过大")
        output = io.BytesIO()
        image.convert("RGBA" if image.mode in {"RGBA", "P"} else "RGB").save(output, format="WEBP", quality=88)
        data = output.getvalue()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / (uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError:
        pass  # Read-only deployment can still serve the fetched image.
    return data
