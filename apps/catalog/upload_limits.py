from apps.catalog.models import SystemSetting

MIN_MB = 1
MAX_MB = 10240
DEFAULTS = {"lv1": 30, "lv2": 100, "lv3": 100}
KEYS = {"lv2": "lv2_upload_limit_mb", "lv3": "lv3_upload_limit_mb"}


def _stored(level):
    key = KEYS.get(level)
    if not key:
        return DEFAULTS[level], None
    row = SystemSetting.objects.filter(pk=key).first()
    try:
        value = int(row.setting_value) if row else DEFAULTS[level]
    except (TypeError, ValueError):
        value = DEFAULTS[level]
    if not MIN_MB <= value <= MAX_MB:
        value = DEFAULTS[level]
    return value, row


def get_upload_limit_settings():
    values = {}
    rows = []
    for level in ("lv1", "lv2", "lv3"):
        mb, row = _stored(level)
        values[level] = {"mb": mb, "bytes": mb * 1024 * 1024, "editable": level != "lv1"}
        if row:
            rows.append(row)
    latest = max(rows, key=lambda item: item.updated_at or "", default=None)
    return {
        "limits": values,
        "minMb": MIN_MB,
        "maxMb": MAX_MB,
        "updatedAt": latest.updated_at if latest else "",
        "updatedBy": latest.updated_by if latest else "",
    }
