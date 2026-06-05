"""
Input validation utilities.
"""
import re
from pathlib import Path

from app.config import ALLOWED_EXTENSIONS, EMAIL_RE


def validate_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def validate_extension(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


def validate_upload_size(size: int, limit: int) -> bool:
    return 0 < size <= limit
