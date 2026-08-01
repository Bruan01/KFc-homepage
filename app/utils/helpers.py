"""General-purpose helper functions."""
import time
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def slugify(value: str) -> str:
    out = []
    for ch in value.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", "_"}:
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or f"product-{int(time.time())}"


def safe_filename(name: str) -> str:
    clean = "".join(ch for ch in name if ch.isalnum() or ch in {".", "-", "_"})
    clean = clean.strip(".")
    return clean or f"package-{int(time.time())}.zip"


def clamp_float_value(value, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def clamp_int_value(value, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def json_safe_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    return str(value)
