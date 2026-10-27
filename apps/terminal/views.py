"""终端 API：配对、令牌下发、账号摘要。

三条硬规则：

1. 配对页走浏览器会话（CSRF 保护），设备接口走 Bearer 令牌（显式豁免 CSRF）。
2. 摘要接口只读，不产生任何积分流水或权益变更。
3. 一块终端只读它绑定账号的数据；解绑即令牌失效。
"""
from __future__ import annotations

import re
from http import HTTPStatus

from django.core.cache import cache
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.core.http import InvalidJSON, client_ip, read_json
from apps.core.permissions import require_user
from apps.core.responses import json_error, json_ok
from apps.notifications.models import Notification
from apps.points.services import PointsError

from .auth import require_device
from .firmware import build_for, update_plan
from .models import STATUS_ACTIVE, STATUS_PENDING, STATUS_REVOKED, TerminalDevice
from .services import (
    checkin_payload,
    issue_token,
    new_pairing_code,
    pair_ttl_seconds,
    pairing_enabled,
    pairing_expiry,
    refresh_seconds,
    summary_payload,
    touch_device,
)
from .textboard import SLOTS, build_board, cjk_available

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{6,64}$")
POLL_INTERVAL = 3
MAX_PAIR_STARTS_PER_HOUR = 60


def _body(request):
    try:
        return read_json(request), None
    except InvalidJSON:
        return None, json_error("invalid json")


def _rate_limited(ip: str) -> bool:
    if not ip:
        return False
    key = f"terminal:pair:start:{ip}"
    added = cache.add(key, 1, timeout=3600)
    if added:
        return False
    try:
        return cache.incr(key) > MAX_PAIR_STARTS_PER_HOUR
    except ValueError:
        cache.set(key, 1, timeout=3600)
        return False


def _device_public(device: TerminalDevice) -> dict:
    return {
        "device_id": device.device_id,
        "name": device.name,
        "status": device.status,
        "hardware": device.hardware,
        "firmware": device.firmware,
        "token_prefix": device.token_prefix,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else "",
        "bound_at": device.bound_at.isoformat() if device.bound_at else "",
        "sync_count": int(device.sync_count),
    }


@csrf_exempt
@require_POST
def pair_start(request):
    """终端上电且没有令牌时调用，拿一个屏幕可读的配对码。"""
    if not pairing_enabled():
        return json_error("pairing disabled", status=HTTPStatus.FORBIDDEN)

    payload, error = _body(request)
    if error is not None:
        return error

    device_id = str(payload.get("device_id", "")).strip()
    if not DEVICE_ID_RE.match(device_id):
        return json_error("invalid device_id")

    hardware = str(payload.get("hardware", ""))[:64]
    firmware = str(payload.get("firmware", ""))[:32]

    # 设备重启后不该重新要码：手上还有未过期的码就原样返回。
    # 这条分支不计入限流，否则反复重启会把配额刷爆（之前就是这样打出 429 的）。
    existing = TerminalDevice.objects.filter(device_id=device_id).first()
    if (
        existing is not None
        and existing.status == STATUS_PENDING
        and existing.pairing_code
        and existing.pairing_expires_at
        and existing.pairing_expires_at > timezone.now()
    ):
        return json_ok(
            {
                "device_id": existing.device_id,
                "pairing_code": existing.pairing_code,
                "expires_in": max(1, int((existing.pairing_expires_at - timezone.now()).total_seconds())),
                "poll_interval": POLL_INTERVAL,
                "bind_url": "/terminal",
                "reused": True,
            }
        )

    ip = client_ip(request)
    if _rate_limited(ip):
        return json_error("too many pair requests, retry later", status=HTTPStatus.TOO_MANY_REQUESTS)

    device, _created = TerminalDevice.objects.get_or_create(
        device_id=device_id,
        defaults={"hardware": hardware, "firmware": firmware},
    )
    # 已绑定的设备也允许重新发码：设备可能被长按重置、刷机或换了主人。
    # 真正的归属变更发生在 confirm——那一步需要登录用户，旧令牌届时失效，
    # 并且会给原主人发一条站内通知。
    if device.status == STATUS_REVOKED:
        device.status = STATUS_PENDING

    device.pairing_code = new_pairing_code()
    device.pairing_expires_at = pairing_expiry()
    device.hardware = hardware or device.hardware
    device.firmware = firmware or device.firmware
    device.save(update_fields=["pairing_code", "pairing_expires_at", "hardware", "firmware", "status"])

    return json_ok(
        {
            "device_id": device.device_id,
            "pairing_code": device.pairing_code,
            "expires_in": pair_ttl_seconds(),
            "poll_interval": POLL_INTERVAL,
            "bind_url": "/terminal",
        }
    )


@csrf_exempt
@require_POST
def pair_poll(request):
    """终端轮询配对结果；成功时一次性拿到令牌明文。"""
    payload, error = _body(request)
    if error is not None:
        return error

    device_id = str(payload.get("device_id", "")).strip()
    code = str(payload.get("code", "")).strip().upper()
    device = TerminalDevice.objects.filter(device_id=device_id).first()
    if device is None:
        return json_error("unknown device", status=HTTPStatus.NOT_FOUND)

    now = timezone.now()
    if device.status == STATUS_ACTIVE and device.pending_token:
        raw = device.pending_token
        TerminalDevice.objects.filter(pk=device.pk).update(
            pending_token="",
            token_delivered_at=now,
            last_seen_at=now,
        )
        return json_ok(
            {
                "status": STATUS_ACTIVE,
                "token": raw,
                "user": device.user.username if device.user_id else "",
                "refresh_seconds": refresh_seconds(),
            }
        )

    if device.status == STATUS_ACTIVE:
        return json_ok({"status": STATUS_ACTIVE, "token": "", "user": device.user.username if device.user_id else ""})

    if device.status == STATUS_REVOKED:
        return json_ok({"status": STATUS_REVOKED})

    expired = device.pairing_expires_at is not None and device.pairing_expires_at <= now
    if expired:
        return json_ok({"status": "expired", "retry_after": POLL_INTERVAL})
    if not code or code != device.pairing_code:
        return json_error("pairing code mismatch", status=HTTPStatus.BAD_REQUEST)

    return json_ok({"status": STATUS_PENDING, "retry_after": POLL_INTERVAL})


@require_user
@require_POST
def pair_confirm(request):
    """浏览器侧输入配对码完成绑定。"""
    payload, error = _body(request)
    if error is not None:
        return error

    code = str(payload.get("code", "")).strip().upper()
    name = str(payload.get("name", "")).strip()[:64]
    if len(code) != 6:
        return json_error("invalid pairing code")

    now = timezone.now()
    with transaction.atomic():
        device = (
            TerminalDevice.objects.select_for_update()
            .filter(pairing_code=code)
            .order_by("-id")
            .first()
        )
        if device is None:
            return json_error("pairing code not found", status=HTTPStatus.NOT_FOUND)
        if device.pairing_expires_at is None or device.pairing_expires_at <= now:
            return json_error("pairing code expired", status=HTTPStatus.GONE)

        previous_owner_id = device.user_id
        raw = issue_token(device)
        device.pending_token = raw
        device.user = request.user
        device.status = STATUS_ACTIVE
        device.bound_at = now
        device.revoked_at = None
        device.name = name or device.name or f"KFlow 终端 {code}"
        device.pairing_code = ""
        device.pairing_expires_at = None
        device.save(
            update_fields=[
                "token_hash",
                "token_prefix",
                "token_issued_at",
                "pending_token",
                "user",
                "status",
                "bound_at",
                "revoked_at",
                "name",
                "pairing_code",
                "pairing_expires_at",
            ]
        )

    if previous_owner_id and previous_owner_id != request.user.pk:
        Notification.objects.create(
            recipient_id=previous_owner_id,
            type="system",
            title="终端已被重新绑定",
            body=f"{device.name or device.device_id} 已被其他账号重新绑定，原绑定已失效。",
        )

    return json_ok({"device": _device_public(device)})


@csrf_exempt
@require_POST
@require_device
def unbind(request):
    """设备自解绑：长按重置时先调这里，服务端放行后才能重新配对。"""
    device = request.terminal_device
    TerminalDevice.objects.filter(pk=device.pk).update(
        status=STATUS_PENDING,
        token_hash="",
        pending_token="",
    )
    return json_ok({"status": STATUS_PENDING})


@require_user
@require_GET
def device_list(request):
    rows = TerminalDevice.objects.filter(user=request.user).order_by("-created_at", "-id")[:50]
    return json_ok({"devices": [_device_public(row) for row in rows]})


@require_user
@require_POST
def device_revoke(request):
    payload, error = _body(request)
    if error is not None:
        return error

    device_id = str(payload.get("device_id", "")).strip()
    device = TerminalDevice.objects.filter(device_id=device_id, user=request.user).first()
    if device is None:
        return json_error("device not found", status=HTTPStatus.NOT_FOUND)

    TerminalDevice.objects.filter(pk=device.pk).update(
        status=STATUS_REVOKED,
        token_hash="",
        pending_token="",
        revoked_at=timezone.now(),
    )
    device.refresh_from_db()
    return json_ok({"device": _device_public(device)})


@csrf_exempt
@require_GET
@require_device
def summary(request):
    """终端主接口：一次请求拿齐屏幕上所有内容。"""
    device = request.terminal_device
    payload = summary_payload(device)
    touch_device(device, ip=client_ip(request))
    return json_ok(payload)


@csrf_exempt
@require_GET
@require_device
def textboard(request):
    """中文正文以 1-bit 位图下发。

    固件只有 ASCII 字库，中文没法在设备上排版；把「画字」这一步搬到服务端，
    排版规则（换行、避头尾、超长截断）改一次 Python 就生效，不用重烧固件。
    返回的是裸二进制，不是 JSON——位图走 JSON 要 base64，体积凭空涨三分之一。
    """
    slot = (request.GET.get("slot") or "murmur").strip().lower()
    if slot not in SLOTS:
        return json_error("unknown slot", status=HTTPStatus.BAD_REQUEST)
    if not cjk_available():
        # 服务器没装中文字体时明确报错，别让屏幕静默显示一片空白。
        return json_error("no CJK font on server", status=HTTPStatus.SERVICE_UNAVAILABLE)

    body = build_board(slot)
    response = HttpResponse(body, content_type="application/octet-stream")
    # 内容随时会变（新碎碎念、新帖），中间层和客户端都别留。
    response["Cache-Control"] = "no-store"
    response["X-Board-Bytes"] = str(len(body))
    return response


@csrf_exempt
@require_POST
@require_device
def checkin(request):
    """屏幕上沿点一下 = 今天首次有效访问。

    这是终端唯一的写接口：不改内容、不投票、只是把「今天来过」记上并给分。
    重复点按是安全的——发分那一步按天幂等，第二次返回 awarded=false。
    """
    device = request.terminal_device
    try:
        payload = checkin_payload(device.user)
    except PointsError as exc:
        return json_error(exc.message, status=exc.status)
    touch_device(device, ip=client_ip(request))
    return json_ok(payload)


# ---------------------------------------------------------------- 固件分发
#
# 这一组接口让板子能自己换掉自己。三条约束：
#
# 1. 全部要设备令牌。固件里没有秘密，但"谁能往我那台设备推固件"必须是可回答的。
# 2. 只读——真正的写发生在设备侧（Update.write）。服务端这里不落任何状态，
#    除了更新 device.firmware 这个"它说自己是几版"的字段。
# 3. 查版本必须传 current 或让服务端用 device.firmware 兜底。不猜：
#    猜错就是"已经最新还反复刷"或者"永远不升"。


@csrf_exempt
@require_GET
@require_device
def firmware_latest(request):
    """我还需要换新固件吗？

    设备每次问都带上自己当前版本；没带就用服务端记着的 device.firmware。
    两者都可能过期（刚刷完还没上报），所以判断只看"最新是否严格大于当前"，
    不做相等才算最新的松判。
    """
    device = request.terminal_device
    current = (request.GET.get("current") or "").strip() or device.firmware
    plan = update_plan(current)
    plan["ok"] = True
    touch_device(device, ip=client_ip(request))
    return json_ok(plan)


@csrf_exempt
@require_GET
@require_device
def firmware_download(request):
    """把 bin 原样吐出去。

    不压缩、不分块、不改名——Update.setMD5() 校验的是字节，中间任何一层
    自作聪明地重编码都会让校验失败。版本号只在已发布的清单里做精确查找，
    传什么都拼不进路径。
    """
    device = request.terminal_device
    version = (request.GET.get("version") or "").strip()
    build = build_for(version)
    if build is None:
        return json_error("unknown firmware version", status=HTTPStatus.NOT_FOUND)

    response = FileResponse(
        build.path.open("rb"),
        content_type="application/octet-stream",
        as_attachment=False,
        filename=build.path.name,
    )
    response["Content-Length"] = str(build.size)
    response["X-Firmware-Version"] = build.version
    response["X-Firmware-MD5"] = build.md5
    # 版本号决定内容，同一个版本号理论上字节永远一样，但仍然别缓存：
    # 覆盖同名 bin 是允许的操作，缓存住就等于让设备刷到旧字节。
    response["Cache-Control"] = "no-store"
    touch_device(device, ip=client_ip(request))
    return response


@csrf_exempt
@require_POST
@require_device
def firmware_report(request):
    """设备升级完回来说一声。

    没有这张回执，服务端就永远以为设备是旧版本，下次一问又推一遍。
    自报版本比服务端推的版本可信——它说的是"我现在跑的是什么"。
    """
    device = request.terminal_device
    try:
        body = read_json(request)
    except InvalidJSON:
        return json_error("invalid json")

    version = str(body.get("version") or "").strip()
    result = str(body.get("result") or "ok").strip().lower()
    if not version or len(version) > 32:
        return json_error("version required")
    if result not in ("ok", "failed"):
        return json_error("result must be ok or failed")

    if result == "ok":
        device.firmware = version
        device.save(update_fields=["firmware"])
    touch_device(device, ip=client_ip(request))
    return json_ok({"ok": True, "version": device.firmware, "result": result})
