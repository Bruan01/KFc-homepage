"""站点群公告接口：前台读取当前公告，后台发布 / 编辑 / 下线。"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .http import InvalidJSON, read_json
from .models import Announcement, AnnouncementImage
from .permissions import require_admin
from .responses import json_error, json_ok

MAX_CONTENT = 600
MAX_POPUP_DAYS = 365
MAX_VALID_DAYS = 3650
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 1600
MAX_IMAGES = 9


def _serialize(row: Announcement) -> dict:
    images = [
        {"id": item.pk, "url": f"/uploads/{item.image}"}
        for item in row.images.all()
    ]
    # 多图上线前的历史公告只有 Announcement.image，这里做兼容回填。
    if not images and row.image:
        images = [{"id": None, "url": f"/uploads/{row.image}"}]
    return {
        "id": row.pk,
        "content": row.content,
        "image_url": images[0]["url"] if images else "",
        "images": images,
        "popup_days": row.popup_days,
        "valid_days": row.valid_days,
        "expires_at": row.expires_at,
        "expired": _is_expired(row),
        "author": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _is_expired(row: Announcement, now: datetime | None = None) -> bool:
    deadline = _parse_time(row.expires_at)
    if deadline is None:
        return False
    return deadline <= (now or timezone.now())


def _deactivate_expired() -> None:
    now = timezone.now()
    for row in Announcement.objects.filter(is_active=True):
        if _is_expired(row, now):
            Announcement.objects.filter(pk=row.pk).update(is_active=False)


def _is_multipart(request) -> bool:
    return (request.content_type or "").lower().startswith("multipart/form-data")


def _read_fields(request) -> dict:
    """兼容 JSON 与 multipart/form-data，返回校验后的公告字段。"""
    remove_image = False
    uploads = []
    keep_ids = None
    if _is_multipart(request):
        data = request.POST
        uploads = list(request.FILES.getlist("images"))
        legacy = request.FILES.get("image")
        if legacy is not None:
            uploads.append(legacy)
        remove_image = str(data.get("remove_image") or "").lower() in {"1", "true", "on"}
        # 新编辑器总会带上 keep_images（可能为空串），据此判断是否按列表保留；
        # 旧客户端不带该字段，沿用“不传新图就保留原图”的行为。
        if "keep_images" in data:
            keep_ids = _parse_ids(data.getlist("keep_images"))
    else:
        try:
            data = read_json(request)
        except InvalidJSON:
            raise ValueError("公告内容格式不正确")
    if len(uploads) > MAX_IMAGES:
        raise ValueError(f"公告最多 {MAX_IMAGES} 张配图")
    content = str(data.get("content") or "").strip()
    if not content:
        raise ValueError("公告内容不能为空")
    if len(content) > MAX_CONTENT:
        raise ValueError(f"公告最多 {MAX_CONTENT} 字")
    popup_days = _read_int(data.get("popup_days"), 3, MAX_POPUP_DAYS, "弹窗频率")
    valid_days = _read_int(data.get("valid_days"), 7, MAX_VALID_DAYS, "有效期")
    return {
        "content": content,
        "popup_days": popup_days,
        "valid_days": valid_days,
        "uploads": uploads,
        "keep_ids": keep_ids,
        "remove_image": remove_image,
    }


def _parse_ids(values) -> list[int]:
    ids = []
    for raw in values:
        for part in str(raw).split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
    return ids


def _read_int(raw, default: int, maximum: int, label: str) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label}需要填写整数天数")
    if value < 0 or value > maximum:
        raise ValueError(f"{label}需在 0 到 {maximum} 天之间")
    return value


def _save_image(upload) -> str:
    if upload.size > MAX_IMAGE_BYTES:
        raise ValueError("图片最大 5MB")
    try:
        from PIL import Image, ImageOps

        Image.open(upload).verify()
        upload.seek(0)
        image = Image.open(upload)
        image.load()
        # EXIF 里才有手机拍摄的旋转信息，不摆正会显示成横躺。
        image = ImageOps.exif_transpose(image) or image
    except Exception:
        raise ValueError("不支持的图片格式，请上传 JPG / PNG / WEBP 图片")

    if image.mode == "P":
        image = image.convert("RGBA")
    elif image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    if max(image.size) > MAX_IMAGE_DIMENSION:
        ratio = MAX_IMAGE_DIMENSION / max(image.size)
        image = image.resize(
            (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
            Image.LANCZOS,
        )
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=82, method=6)
    return default_storage.save(f"announcements/{uuid.uuid4().hex}.webp", ContentFile(buf.getvalue()))


def _delete_image(path: str) -> None:
    if not path:
        return
    try:
        default_storage.delete(path)
    except Exception:
        pass


def _save_images(uploads) -> list[str]:
    paths = []
    try:
        for upload in uploads:
            paths.append(_save_image(upload))
    except Exception:
        for path in paths:
            _delete_image(path)
        raise
    return paths


def _expires_at(valid_days: int, base: datetime | None = None) -> str:
    if valid_days <= 0:
        return ""
    return ((base or timezone.now()) + timedelta(days=valid_days)).isoformat()


def _broadcast(row: Announcement) -> None:
    """新公告发布后给所有用户各写一条站内通知。"""
    try:
        from django.contrib.auth import get_user_model

        from apps.notifications.models import Notification

        user_ids = get_user_model().objects.values_list("pk", flat=True).iterator(chunk_size=500)
        link = f"/?announcement={row.pk}"
        batch = []
        for user_id in user_ids:
            batch.append(Notification(
                recipient_id=user_id, type="system", title="站点公告",
                body=row.content[:300], link=link,
            ))
            if len(batch) >= 500:
                Notification.objects.bulk_create(batch)
                batch = []
        if batch:
            Notification.objects.bulk_create(batch)
    except Exception:
        pass


@require_GET
def current(request):
    rows = Announcement.objects.filter(is_active=True).prefetch_related("images").order_by("-updated_at", "-id")
    row = rows.first()
    if row and _is_expired(row):
        Announcement.objects.filter(pk=row.pk).update(is_active=False)
        row = None
    return json_ok({"item": _serialize(row) if row else None})


@require_admin(level=3)
@require_http_methods(["GET", "POST"])
def admin_collection(request):
    if request.method == "GET":
        _deactivate_expired()
        rows = list(Announcement.objects.prefetch_related("images").order_by("-id")[:10])
        active = next((row for row in rows if row.is_active), None)
        return json_ok({"active": _serialize(active) if active else None, "items": [_serialize(row) for row in rows]})
    try:
        fields = _read_fields(request)
    except ValueError as exc:
        return json_error(str(exc))
    try:
        paths = _save_images(fields["uploads"])
    except ValueError as exc:
        return json_error(str(exc))

    now = timezone.now()
    try:
        with transaction.atomic():
            Announcement.objects.filter(is_active=True).update(is_active=False)
            row = Announcement.objects.create(
                content=fields["content"],
                image=paths[0] if paths else "",
                popup_days=fields["popup_days"],
                valid_days=fields["valid_days"],
                expires_at=_expires_at(fields["valid_days"], now),
                is_active=True,
                created_by=request.kflow_admin["username"],
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
            if paths:
                AnnouncementImage.objects.bulk_create([
                    AnnouncementImage(announcement=row, image=path, position=index)
                    for index, path in enumerate(paths)
                ])
    except Exception:
        for path in paths:
            _delete_image(path)
        raise
    _broadcast(row)
    return json_ok({"item": _serialize(row)}, status=201)


@require_admin(level=3)
@require_http_methods(["POST", "DELETE"])
def admin_detail(request, announcement_id: int):
    row = Announcement.objects.filter(pk=announcement_id).first()
    if not row:
        return json_error("公告不存在", status=404)
    if request.method == "DELETE":
        if row.is_active:
            row.is_active = False
            row.updated_at = timezone.now().isoformat()
            row.save(update_fields=["is_active", "updated_at"])
        return json_ok({"item": _serialize(row)})
    try:
        fields = _read_fields(request)
    except ValueError as exc:
        return json_error(str(exc))

    existing = list(row.images.all())
    if fields["keep_ids"] is None:
        # 旧客户端：不传新图就沿用原图，remove_image 表示清空。
        kept = [] if fields["remove_image"] else existing
    else:
        by_id = {item.pk: item for item in existing}
        kept = [by_id[pk] for pk in fields["keep_ids"] if pk in by_id]
    if len(kept) + len(fields["uploads"]) > MAX_IMAGES:
        return json_error(f"公告最多 {MAX_IMAGES} 张配图")
    try:
        new_paths = _save_images(fields["uploads"])
    except ValueError as exc:
        return json_error(str(exc))

    kept_ids = [item.pk for item in kept]
    keep_paths = {item.image for item in kept} | set(new_paths)
    removed_paths = {item.image for item in existing} - keep_paths

    try:
        with transaction.atomic():
            if new_paths:
                AnnouncementImage.objects.bulk_create([
                    AnnouncementImage(
                        announcement=row, image=path, position=len(kept) + offset,
                    )
                    for offset, path in enumerate(new_paths)
                ])
            stale_ids = [item.pk for item in existing if item.pk not in kept_ids]
            if stale_ids:
                AnnouncementImage.objects.filter(pk__in=stale_ids).delete()
            for index, item in enumerate(kept):
                if item.position != index:
                    AnnouncementImage.objects.filter(pk=item.pk).update(position=index)

            row.content = fields["content"]
            row.popup_days = fields["popup_days"]
            row.valid_days = fields["valid_days"]
            row.updated_at = timezone.now().isoformat()
            if row.is_active:
                row.expires_at = _expires_at(fields["valid_days"])
            row.image = kept[0].image if kept else (new_paths[0] if new_paths else "")
            row.save()
    except Exception:
        for path in new_paths:
            _delete_image(path)
        raise
    for path in removed_paths:
        _delete_image(path)
    return json_ok({"item": _serialize(row)})
