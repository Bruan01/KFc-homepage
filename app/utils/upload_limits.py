"""
Upload limit settings helpers.
"""
from app.config import (
    LV1_UPLOAD_SIZE_LIMIT,
    LV2_UPLOAD_SIZE_LIMIT,
    LV3_UPLOAD_SIZE_LIMIT,
)
from app.db import get_db
from app.utils.helpers import now_iso

UPLOAD_LIMIT_MIN_MB = 1
UPLOAD_LIMIT_MAX_MB = 10240

_SETTING_KEYS = {
    "lv2": "lv2_upload_limit_mb",
    "lv3": "lv3_upload_limit_mb",
}


def _bytes_to_mb(limit_bytes: int) -> int:
    return max(1, int(limit_bytes // (1024 * 1024)))


def _default_limit_mb(level: str) -> int:
    if level == "lv1":
        return _bytes_to_mb(LV1_UPLOAD_SIZE_LIMIT)
    if level == "lv2":
        return _bytes_to_mb(LV2_UPLOAD_SIZE_LIMIT)
    return _bytes_to_mb(LV3_UPLOAD_SIZE_LIMIT)


def _coerce_stored_mb(raw_value, fallback: int) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return fallback
    if parsed < UPLOAD_LIMIT_MIN_MB or parsed > UPLOAD_LIMIT_MAX_MB:
        return fallback
    return parsed


def _serialize_level(mb: int, editable: bool) -> dict:
    return {
        "mb": int(mb),
        "bytes": int(mb) * 1024 * 1024,
        "editable": bool(editable),
    }


def _row_value(row, key: str, default=None):
    if row is None:
        return default
    try:
        return row[key]
    except Exception:
        return default


def get_upload_limit_settings(conn=None) -> dict:
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT setting_key, setting_value, updated_at, updated_by
            FROM system_settings
            WHERE setting_key IN (?, ?)
            """,
            (_SETTING_KEYS["lv2"], _SETTING_KEYS["lv3"]),
        ).fetchall()
        stored = {str(row["setting_key"]): row for row in rows}

        lv1_mb = _default_limit_mb("lv1")
        lv2_mb = _coerce_stored_mb(_row_value(stored.get(_SETTING_KEYS["lv2"]), "setting_value"), _default_limit_mb("lv2"))
        lv3_mb = _coerce_stored_mb(_row_value(stored.get(_SETTING_KEYS["lv3"]), "setting_value"), _default_limit_mb("lv3"))

        latest_row = None
        for row in rows:
            updated_at = str(row["updated_at"] or "")
            if not latest_row or updated_at > str(latest_row["updated_at"] or ""):
                latest_row = row

        return {
            "limits": {
                "lv1": _serialize_level(lv1_mb, editable=False),
                "lv2": _serialize_level(lv2_mb, editable=True),
                "lv3": _serialize_level(lv3_mb, editable=True),
            },
            "minMb": UPLOAD_LIMIT_MIN_MB,
            "maxMb": UPLOAD_LIMIT_MAX_MB,
            "updatedAt": str((latest_row["updated_at"] if latest_row else "") or ""),
            "updatedBy": str((latest_row["updated_by"] if latest_row else "") or ""),
        }
    finally:
        if own_conn and conn is not None:
            conn.close()


def get_effective_upload_limit_bytes(admin_level: int, conn=None) -> int:
    settings = get_upload_limit_settings(conn)
    if int(admin_level) >= 3:
        return int(settings["limits"]["lv3"]["bytes"])
    if int(admin_level) >= 2:
        return int(settings["limits"]["lv2"]["bytes"])
    return int(settings["limits"]["lv1"]["bytes"])


def validate_upload_limit_payload(body) -> tuple[dict | None, str | None]:
    result = {}
    for level, key in _SETTING_KEYS.items():
        label = f"{level.upper()} upload limit"
        raw_value = body.get(key)
        if raw_value is None or str(raw_value).strip() == "":
            return None, f"{label} required"
        try:
            mb = int(raw_value)
        except (TypeError, ValueError):
            return None, f"{label} must be an integer MB value"
        if mb < UPLOAD_LIMIT_MIN_MB or mb > UPLOAD_LIMIT_MAX_MB:
            return None, f"{label} must be between {UPLOAD_LIMIT_MIN_MB}MB and {UPLOAD_LIMIT_MAX_MB}MB"
        result[key] = mb

    if result[_SETTING_KEYS["lv3"]] < result[_SETTING_KEYS["lv2"]]:
        return None, "LV3 upload limit must be greater than or equal to LV2"

    return result, None


def save_upload_limit_settings(conn, payload: dict, updated_by: str) -> None:
    updated_at = now_iso()
    for key in (_SETTING_KEYS["lv2"], _SETTING_KEYS["lv3"]):
        conn.execute(
            """
            INSERT INTO system_settings (setting_key, setting_value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(setting_key)
            DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (key, str(int(payload[key])), updated_at, str(updated_by or "").strip()),
        )
