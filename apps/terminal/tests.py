# pyright: reportMissingImports=false
"""终端接入层测试：配对、令牌一次性下发、摘要只读、吊销。"""
from __future__ import annotations

import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.points.models import PointAccount

from .models import (
    STATUS_ACTIVE,
    STATUS_REVOKED,
    HardwareReservation,
    TerminalDevice,
)
from .services import hash_token

DEVICE_ID = "esp32s3-A1B2C3"


def make_user(username: str = "kieran") -> User:
    return User.objects.create(
        username=username,
        password="",
        email=f"{username}@example.com",
        created_at="2026-10-01T00:00:00+00:00",
        display_name="Kieran",
    )


class PairingFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user()

    def _start(self) -> dict:
        response = self.client.post(
            "/api/terminal/pair/start",
            data=json.dumps({"device_id": DEVICE_ID, "hardware": "esp32s3-ili9341", "firmware": "0.1.0"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_pair_start_creates_pending_device_with_code(self):
        data = self._start()
        self.assertEqual(len(data["pairing_code"]), 6)
        device = TerminalDevice.objects.get(device_id=DEVICE_ID)
        self.assertEqual(device.status, "pending")
        self.assertEqual(device.pairing_code, data["pairing_code"])
        self.assertGreater(device.pairing_expires_at, timezone.now())

    def test_pair_start_rejects_bad_device_id(self):
        response = self.client.post(
            "/api/terminal/pair/start",
            data=json.dumps({"device_id": "bad id!"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_confirm_requires_login(self):
        code = self._start()["pairing_code"]
        response = self.client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, (401, 403))

    def test_confirm_binds_device_to_current_user(self):
        code = self._start()["pairing_code"]
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code, "name": "书桌屏"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        device = TerminalDevice.objects.get(device_id=DEVICE_ID)
        self.assertEqual(device.status, STATUS_ACTIVE)
        self.assertEqual(device.user_id, self.user.pk)
        self.assertEqual(device.name, "书桌屏")
        self.assertTrue(device.token_hash)
        self.assertEqual(device.pairing_code, "")

    def test_poll_delivers_token_exactly_once(self):
        code = self._start()["pairing_code"]
        self.client.force_login(self.user)
        self.client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        self.client.logout()

        first = self.client.post(
            "/api/terminal/pair/poll",
            data=json.dumps({"device_id": DEVICE_ID, "code": code}),
            content_type="application/json",
        ).json()
        self.assertEqual(first["status"], "active")
        token = first["token"]
        self.assertTrue(token)

        device = TerminalDevice.objects.get(device_id=DEVICE_ID)
        self.assertEqual(device.token_hash, hash_token(token))
        self.assertEqual(device.pending_token, "")
        self.assertIsNotNone(device.token_delivered_at)

        second = self.client.post(
            "/api/terminal/pair/poll",
            data=json.dumps({"device_id": DEVICE_ID, "code": code}),
            content_type="application/json",
        ).json()
        self.assertEqual(second["token"], "")

    def test_expired_code_cannot_bind(self):
        code = self._start()["pairing_code"]
        TerminalDevice.objects.filter(device_id=DEVICE_ID).update(
            pairing_expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 410)

    def test_bound_device_can_request_a_new_pairing_code(self):
        """长按重置 / 刷机后设备会重新要码，不能直接 409 把人卡死。"""
        code = self._start()["pairing_code"]
        self.client.force_login(self.user)
        self.client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        response = self.client.post(
            "/api/terminal/pair/start",
            data=json.dumps({"device_id": DEVICE_ID}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["pairing_code"]), 6)

    def test_rebind_notifies_previous_owner_and_rotates_token(self):
        code = self._start()["pairing_code"]
        self.client.force_login(self.user)
        self.client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        old_hash = TerminalDevice.objects.get(device_id=DEVICE_ID).token_hash

        code2 = self._start()["pairing_code"]
        self.client.force_login(make_user("second-owner"))
        response = self.client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code2}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)

        device = TerminalDevice.objects.get(device_id=DEVICE_ID)
        self.assertNotEqual(device.token_hash, old_hash)
        self.assertEqual(device.user.username, "second-owner")
        self.assertEqual(
            Notification.objects.filter(recipient=self.user, title="终端已被重新绑定").count(), 1
        )

    def test_device_can_unbind_itself_then_repair(self):
        code = self._start()["pairing_code"]
        self.client.force_login(self.user)
        self.client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        token = self.client.post(
            "/api/terminal/pair/poll",
            data=json.dumps({"device_id": DEVICE_ID, "code": code}),
            content_type="application/json",
        ).json()["token"]
        self.client.logout()

        released = self.client.post(
            "/api/terminal/unbind",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(released.status_code, 200, released.content)

        device = TerminalDevice.objects.get(device_id=DEVICE_ID)
        self.assertEqual(device.status, "pending")
        self.assertEqual(device.token_hash, "")

        # 解绑后旧令牌失效，重新配对不再 409
        self.assertEqual(
            self.client.get("/api/terminal/summary", HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 401
        )
        again = self.client.post(
            "/api/terminal/pair/start",
            data=json.dumps({"device_id": DEVICE_ID}),
            content_type="application/json",
        )
        self.assertEqual(again.status_code, 200)


class SummaryTests(TestCase):
    def setUp(self):
        self.user = make_user()
        PointAccount.objects.create(
            user=self.user,
            balance=128,
            total_earned=200,
            total_spent=72,
            reputation_level=3,
            consecutive_active_days=7,
            updated_at=timezone.now().isoformat(),
        )
        Notification.objects.create(recipient=self.user, type="reply", title="有人回复了你的帖子")
        Notification.objects.create(recipient=self.user, type="badge", title="获得「初次发声」勋章")
        self.device = TerminalDevice.objects.create(
            device_id=DEVICE_ID,
            user=self.user,
            name="书桌屏",
            status=STATUS_ACTIVE,
            token_hash=hash_token("t" * 43),
            token_prefix="tttttttt",
            firmware="0.1.0",
        )

    def _get(self, token: str = "t" * 43):
        return self.client.get("/api/terminal/summary", HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_summary_requires_token(self):
        self.assertEqual(self.client.get("/api/terminal/summary").status_code, 401)
        self.assertEqual(self._get("wrong-token-value-123").status_code, 401)

    def test_summary_returns_account_glance(self):
        response = self._get()
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["user"]["username"], "kieran")
        self.assertEqual(data["points"]["balance"], 128)
        self.assertEqual(data["points"]["streak"], 7)
        self.assertEqual(data["notifications"]["unread"], 2)
        self.assertEqual(len(data["notifications"]["items"]), 2)
        self.assertEqual(data["notifications"]["items"][0]["label"], "BADGE")
        self.assertGreaterEqual(data["refresh_seconds"], 60)

    def test_summary_is_read_only(self):
        before = PointAccount.objects.get(user=self.user).balance
        self._get()
        after = PointAccount.objects.get(user=self.user).balance
        self.assertEqual(before, after)
        self.assertEqual(self.user.notifications.filter(is_read=False).count(), 2)

    def test_summary_increments_sync_count(self):
        self._get()
        self.device.refresh_from_db()
        self.assertEqual(self.device.sync_count, 1)
        self.assertIsNotNone(self.device.last_seen_at)

    def test_revoke_invalidates_token(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/terminal/devices/revoke",
            data=json.dumps({"device_id": DEVICE_ID}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, STATUS_REVOKED)
        self.assertEqual(self.device.token_hash, "")
        self.assertEqual(self._get().status_code, 401)

    def test_revoke_requires_ownership(self):
        other = make_user("someone-else")
        self.client.force_login(other)
        response = self.client.post(
            "/api/terminal/devices/revoke",
            data=json.dumps({"device_id": DEVICE_ID}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_device_list_only_shows_own_devices(self):
        TerminalDevice.objects.create(device_id="esp32s3-OTHER1", user=make_user("other"), status=STATUS_ACTIVE)
        self.client.force_login(self.user)
        data = self.client.get("/api/terminal/devices").json()
        self.assertEqual([row["device_id"] for row in data["devices"]], [DEVICE_ID])


class CheckinTests(TestCase):
    """屏幕顶端点一下 = 今天首次有效访问。按天幂等，连点不会重复发分。"""

    def setUp(self):
        self.user = make_user()
        PointAccount.objects.create(
            user=self.user,
            balance=128,
            total_earned=200,
            total_spent=72,
            consecutive_active_days=7,
            updated_at=timezone.now().isoformat(),
        )
        self.device = TerminalDevice.objects.create(
            device_id=DEVICE_ID,
            user=self.user,
            name="书桌屏",
            status=STATUS_ACTIVE,
            token_hash=hash_token("t" * 43),
            token_prefix="tttttttt",
            firmware="0.4.1",
        )

    def _post(self, token: str = "t" * 43):
        return self.client.post(
            "/api/terminal/checkin",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_checkin_requires_device_token(self):
        response = self.client.post(
            "/api/terminal/checkin", data=json.dumps({}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)

    def test_first_checkin_awards_points_once(self):
        first = self._post()
        self.assertEqual(first.status_code, 200, first.content)
        data = first.json()
        self.assertTrue(data["awarded"])
        self.assertEqual(data["points"], 2)
        self.assertEqual(data["balance"], 130)
        self.assertTrue(data["done"])

        second = self._post().json()
        self.assertFalse(second["awarded"])
        self.assertEqual(second["points"], 0)
        self.assertEqual(second["balance"], 130)

    def test_checkin_is_reflected_in_summary(self):
        before = self.client.get(
            "/api/terminal/summary", HTTP_AUTHORIZATION="Bearer " + "t" * 43
        ).json()
        self.assertFalse(before["checkin"]["done"])
        self.assertGreaterEqual(before["checkin"]["reward"], 0)

        self._post()
        after = self.client.get(
            "/api/terminal/summary", HTTP_AUTHORIZATION="Bearer " + "t" * 43
        ).json()
        self.assertTrue(after["checkin"]["done"])
        self.assertEqual(after["points"]["balance"], 130)

    def test_checkin_writes_a_single_daily_ledger_row(self):
        from apps.points.models import PointLedger

        self._post()
        self._post()
        self.assertEqual(
            PointLedger.objects.filter(user=self.user, event_type="daily_activity").count(), 1
        )


class CsrfBoundaryTests(TestCase):
    """浏览器接口必须带 CSRF，设备接口必须豁免——两边不能串味。"""

    def setUp(self):
        self.user = make_user("csrf-user")

    def _start_code(self) -> str:
        response = Client().post(
            "/api/terminal/pair/start",
            data=json.dumps({"device_id": "esp32s3-CSRF01"}),
            content_type="application/json",
        )
        return response.json()["pairing_code"]

    def test_pair_confirm_requires_csrf_and_accepts_page_token(self):
        code = self._start_code()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        blocked = client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        self.assertEqual(blocked.status_code, 403)

        page = client.get("/terminal")
        self.assertEqual(page.status_code, 200)
        csrf = page.cookies["csrftoken"].value

        allowed = client.post(
            "/api/terminal/pair/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(allowed.status_code, 200, allowed.content)

    def test_device_endpoints_are_csrf_exempt(self):
        code = self._start_code()
        client = Client(enforce_csrf_checks=True)
        polled = client.post(
            "/api/terminal/pair/poll",
            data=json.dumps({"device_id": "esp32s3-CSRF01", "code": code}),
            content_type="application/json",
        )
        self.assertEqual(polled.status_code, 200)


class RateLimitTests(TestCase):
    """重启风暴不能把自己打成 429：有效的码要原样复用。"""

    def setUp(self):
        self.client = Client()

    def _start(self):
        return self.client.post(
            "/api/terminal/pair/start",
            data=json.dumps({"device_id": "esp32s3-REUSE1"}),
            content_type="application/json",
        )

    def test_valid_code_is_reused_without_hitting_limit(self):
        first = self._start()
        self.assertEqual(first.status_code, 200)
        code = first.json()["pairing_code"]

        for _ in range(40):
            again = self._start()
            self.assertEqual(again.status_code, 200)
            self.assertEqual(again.json()["pairing_code"], code)
            self.assertTrue(again.json().get("reused"))


class TextboardTests(TestCase):
    """中文正文以 1-bit 位图下发。设备端没有字库，这里守住格式与降级。"""

    def setUp(self):
        self.user = make_user()
        self.device = TerminalDevice.objects.create(
            device_id=DEVICE_ID,
            user=self.user,
            name="书桌屏",
            status=STATUS_ACTIVE,
            token_hash=hash_token("t" * 43),
            token_prefix="tttttttt",
            firmware="0.5.0",
        )

    def _get(self, slot: str = "murmur", token: str = "t" * 43):
        return self.client.get(
            f"/api/terminal/textboard?slot={slot}", HTTP_AUTHORIZATION=f"Bearer {token}"
        )

    @staticmethod
    def _blocks(raw: bytes):
        """按固件的方式解包：u16 count，然后每块 12 字节头 + stride*h 字节。"""
        import struct

        count = struct.unpack_from("<H", raw, 0)[0]
        off = 2
        out = []
        for _ in range(count):
            x, y, w, h, stride, color = struct.unpack_from("<HHHHHH", raw, off)
            off += 12
            out.append((x, y, w, h, stride, color, raw[off : off + stride * h]))
            off += stride * h
        return out, off

    def test_textboard_requires_device_token(self):
        self.assertEqual(self.client.get("/api/terminal/textboard?slot=murmur").status_code, 401)

    def test_unknown_slot_is_rejected(self):
        self.assertEqual(self._get("nope").status_code, 400)
        self.assertEqual(self._get("../../etc/passwd").status_code, 400)

    def test_binary_shape_matches_firmware_parser(self):
        from apps.murmurs.models import Murmur

        Murmur.objects.create(author_username="kieran", content="今天把中文弄上屏了", client_key="m1")
        response = self._get("murmur")
        if response.status_code == 503:
            self.skipTest("server has no CJK font installed")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        raw = response.content
        blocks, consumed = self._blocks(raw)
        self.assertGreaterEqual(len(blocks), 2)
        # 正好读完：多一个字节少一个字节都会让固件的"取满即止"判断出错。
        self.assertEqual(consumed, len(raw))
        for _x, _y, w, _h, stride, _color, data in blocks:
            self.assertEqual(stride, (w + 7) // 8)
            self.assertEqual(len(data), stride * _h)

    def test_chinese_actually_has_ink(self):
        """渲染出来的正文块必须有实心像素，否则只是"接口通了、屏幕还是白板"。"""
        from apps.murmurs.models import Murmur

        Murmur.objects.create(author_username="kieran", content="今天把中文弄上屏了", client_key="m2")
        response = self._get("murmur")
        if response.status_code == 503:
            self.skipTest("server has no CJK font installed")

        blocks, _ = self._blocks(response.content)
        body = blocks[-1][6]  # 最后一块是正文
        ink = sum(bin(byte).count("1") for byte in body)
        self.assertGreater(ink, 100)

    def test_topic_falls_back_when_empty(self):
        """没有新帖时也要给出一块能看的占位，不能回空 body。"""
        response = self._get("topic")
        if response.status_code == 503:
            self.skipTest("server has no CJK font installed")
        self.assertEqual(response.status_code, 200)
        blocks, _ = self._blocks(response.content)
        self.assertGreaterEqual(len(blocks), 1)


class FirmwareDistributionTests(TestCase):
    """固件分发：版本判断、字节一致性、以及"传什么都拼不进路径"。

    签名从 v0.10.0 起是硬要求，所以这里的夹具**真的签一遍**，不把
    TERMINAL_FIRMWARE_REQUIRE_SIG 关掉：关掉开关之后测出来的绿是假的，
    生产上开关是开着的。密钥是每次跑测试现生成的，不落盘、不入库。
    """

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.user = make_user()
        self.device = TerminalDevice.objects.create(
            device_id=DEVICE_ID,
            user=self.user,
            name="书桌屏",
            status=STATUS_ACTIVE,
            token_hash=hash_token("f" * 43),
            token_prefix="ffffffff",
            firmware="0.5.0",
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(TERMINAL_FIRMWARE_DIR=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)

        # 测试用密钥对：私钥只在内存里，公钥写成 PEM 给服务端验签用。
        from pathlib import Path

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        self.signing_key = ec.generate_private_key(ec.SECP256R1())
        pub_path = Path(self.tmp.name) / "ota_pubkey.pem"
        pub_path.write_bytes(
            self.signing_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        key_override = override_settings(TERMINAL_FIRMWARE_PUBKEY=str(pub_path))
        key_override.enable()
        self.addCleanup(key_override.disable)

    # -- 工具 ------------------------------------------------------------

    def _sign(self, path, key=None):
        """给 bin 写一个 .sig 边车文件，模拟 scripts/sign_firmware.py sign。"""
        import base64
        import hashlib

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        signer = key or self.signing_key
        digest = hashlib.sha256(path.read_bytes()).digest()
        sig = signer.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        path.with_suffix(".sig").write_text(base64.b64encode(sig).decode() + "\n")
        return sig

    def _publish(self, version: str, payload: bytes = b"\xE9" * 4096, sign: bool = True):
        from pathlib import Path

        path = Path(self.tmp.name) / f"kflow_terminal-{version}.bin"
        path.write_bytes(payload)
        if sign:
            self._sign(path)
        return path

    def _latest(self, current: str | None = None):
        url = "/api/terminal/firmware/latest"
        if current is not None:
            url += f"?current={current}"
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {'f' * 43}")

    def _download(self, version: str):
        return self.client.get(
            f"/api/terminal/firmware/download?version={version}",
            HTTP_AUTHORIZATION=f"Bearer {'f' * 43}",
        )

    # -- 鉴权与空目录 ----------------------------------------------------

    def test_requires_device_token(self):
        self.assertEqual(self.client.get("/api/terminal/firmware/latest").status_code, 401)
        self.assertEqual(
            self.client.get("/api/terminal/firmware/download?version=0.6.0").status_code, 401
        )

    def test_empty_directory_is_not_an_error(self):
        """还没发布过任何固件时，设备应该得到"没有更新"，而不是 500。"""
        body = self._latest().json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["update_available"])
        self.assertEqual(body["reason"], "no build published")

    # -- 版本判断 --------------------------------------------------------

    def test_reports_newer_build(self):
        self._publish("0.6.0")
        body = self._latest("0.5.0").json()
        self.assertTrue(body["update_available"])
        self.assertEqual(body["latest"], "0.6.0")
        self.assertEqual(body["size"], 4096)
        self.assertIn("version=0.6.0", body["url"])

    def test_same_version_is_not_an_update(self):
        self._publish("0.5.0")
        self.assertFalse(self._latest("0.5.0").json()["update_available"])

    def test_older_build_never_downgrades(self):
        """目录里留着旧 bin 不该把新设备往回刷。"""
        self._publish("0.4.0")
        self.assertFalse(self._latest("0.5.0").json()["update_available"])

    def test_falls_back_to_device_recorded_version(self):
        """固件不带 current 时用 device.firmware 兜底，不能当成 0.0.0。"""
        self._publish("0.5.0")
        self.assertFalse(self._latest().json()["update_available"])
        self._publish("0.9.0")
        self.assertTrue(self._latest().json()["update_available"])

    def test_picks_highest_version_and_ignores_junk_files(self):
        from pathlib import Path

        self._publish("0.5.1")
        self._publish("0.10.0")  # 字符串比较会把它排在 0.5.1 前面，数值比较才对
        self._publish("0.4.0")
        (Path(self.tmp.name) / "notes.txt").write_text("ignore me")
        (Path(self.tmp.name) / "kflow_terminal-latest.bin").write_bytes(b"\x00")
        self.assertEqual(self._latest("0.5.0").json()["latest"], "0.10.0")

    def test_version_tuple_tolerates_prefix_and_garbage(self):
        from .firmware import version_tuple

        self.assertEqual(version_tuple("v0.5.0"), (0, 5, 0))
        self.assertEqual(version_tuple("0.5"), (0, 0, 0))
        self.assertEqual(version_tuple(""), (0, 0, 0))
        self.assertEqual(version_tuple("nonsense"), (0, 0, 0))

    # -- 签名 ------------------------------------------------------------
    #
    # 这一组测的是"发布流程出错时清单会怎么说"。设备端的验签是另一层
    # （mbedtls + 内嵌公钥），这里管的是别把一个注定被拒的包发出去——
    # 那会让设备每次都白下一整包 1.2MB，人还以为是网络慢。

    def test_manifest_carries_signature_and_sha256(self):
        import base64
        import hashlib

        payload = bytes(range(256)) * 8
        self._publish("0.6.0", payload)
        body = self._latest("0.5.0").json()
        self.assertTrue(body["update_available"])
        self.assertTrue(body["signed"])
        self.assertEqual(body["sha256"], hashlib.sha256(payload).hexdigest())
        sig = base64.b64decode(body["sig"])
        self.assertEqual(sig[0], 0x30)  # DER SEQUENCE
        self.assertLessEqual(len(sig), 72)

    def test_unsigned_build_is_not_offered(self):
        self._publish("0.10.0", sign=False)
        body = self._latest("0.5.0").json()
        self.assertFalse(body["update_available"])
        self.assertIn("not usable", body["reason"])
        self.assertEqual(body["latest"], "0.10.0")

    def test_tampered_bin_is_caught_before_download(self):
        from pathlib import Path

        path = self._publish("0.6.0")
        data = bytearray(Path(path).read_bytes())
        data[0] ^= 0xFF  # 改一个字节，签名还是旧的
        Path(path).write_bytes(bytes(data))
        body = self._latest("0.5.0").json()
        self.assertFalse(body["update_available"])
        self.assertIn("does not match", body["reason"])

    def test_signature_from_another_key_is_rejected(self):
        from pathlib import Path

        from cryptography.hazmat.primitives.asymmetric import ec

        path = Path(self.tmp.name) / "kflow_terminal-0.6.0.bin"
        path.write_bytes(b"\xE9" * 4096)
        self._sign(path, ec.generate_private_key(ec.SECP256R1()))
        body = self._latest("0.5.0").json()
        self.assertFalse(body["update_available"])
        self.assertIn("does not match", body["reason"])

    def test_garbage_sig_file_is_reported(self):
        from pathlib import Path

        path = self._publish("0.6.0")
        Path(path).with_suffix(".sig").write_text("not base64 !!!")
        body = self._latest("0.5.0").json()
        self.assertFalse(body["update_available"])
        self.assertIn("base64", body["reason"])

    # -- 下载 ------------------------------------------------------------

    def test_download_returns_exact_bytes(self):
        import hashlib

        payload = bytes(range(256)) * 8
        self._publish("0.6.0", payload)
        response = self._download("0.6.0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        # 差一个字节 Update.setMD5() 就会拒绝，所以这里必须逐字节相等。
        self.assertEqual(b"".join(response.streaming_content), payload)
        self.assertEqual(response["X-Firmware-MD5"], hashlib.md5(payload).hexdigest())
        self.assertEqual(response["X-Firmware-SHA256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(response["X-Firmware-Version"], "0.6.0")

    def test_download_rejects_unknown_and_traversal(self):
        self._publish("0.6.0")
        self.assertEqual(self._download("9.9.9").status_code, 404)
        self.assertEqual(self._download("../../etc/passwd").status_code, 404)
        self.assertEqual(self._download("").status_code, 404)

    # -- 回执 ------------------------------------------------------------

    def _report(self, payload: dict):
        return self.client.post(
            "/api/terminal/firmware/report",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {'f' * 43}",
        )

    def test_report_updates_recorded_version(self):
        response = self._report({"version": "0.6.0", "result": "ok"})
        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertEqual(self.device.firmware, "0.6.0")

    def test_failed_report_does_not_change_version(self):
        """升级失败时设备跑的还是老版本，服务端不能跟着改。"""
        self._report({"version": "0.6.0", "result": "failed"})
        self.device.refresh_from_db()
        self.assertEqual(self.device.firmware, "0.5.0")

    def test_report_validates_payload(self):
        self.assertEqual(self._report({"result": "ok"}).status_code, 400)
        self.assertEqual(self._report({"version": "0.6.0", "result": "maybe"}).status_code, 400)


class NoticeSignalTests(TestCase):
    """主动提醒的信号源：设备只认 latest_id 这个整数，这里守住它的语义。"""

    def setUp(self):
        self.user = make_user()
        self.device = TerminalDevice.objects.create(
            device_id=DEVICE_ID,
            user=self.user,
            name="书桌屏",
            status=STATUS_ACTIVE,
            token_hash=hash_token("n" * 43),
            token_prefix="nnnnnnnn",
            firmware="0.7.0",
        )

    def _summary(self):
        return self.client.get(
            "/api/terminal/summary", HTTP_AUTHORIZATION=f"Bearer {'n' * 43}"
        ).json()

    def _notify(self, title: str, *, is_read: bool = False):
        from apps.notifications.models import Notification

        return Notification.objects.create(
            recipient=self.user, type="reply", title=title, is_read=is_read
        )

    def test_no_notifications_means_zero(self):
        body = self._summary()
        self.assertEqual(body["notifications"]["latest_id"], 0)
        self.assertEqual(body["notifications"]["unread"], 0)
        self.assertEqual(body["notifications"]["items"], [])

    def test_latest_id_tracks_new_arrival(self):
        first = self._notify("第一条")
        self.assertEqual(self._summary()["notifications"]["latest_id"], first.id)
        second = self._notify("第二条")
        self.assertEqual(self._summary()["notifications"]["latest_id"], second.id)
        self.assertGreater(second.id, first.id)

    def test_latest_id_survives_marking_read(self):
        """读掉之后 id 不能退回去，否则设备会以为又来了一条。"""
        row = self._notify("会读掉的")
        before = self._summary()["notifications"]["latest_id"]
        row.is_read = True
        row.save(update_fields=["is_read"])
        body = self._summary()
        self.assertEqual(body["notifications"]["latest_id"], before)
        self.assertEqual(body["notifications"]["unread"], 0)

    def test_items_carry_id_and_read_flag(self):
        row = self._notify("带 id 的")
        item = self._summary()["notifications"]["items"][0]
        self.assertEqual(item["id"], row.id)
        self.assertFalse(item["is_read"])
        self.assertIn("label", item)


class ReservationTests(TestCase):
    """硬件小 K 预约：一人一码、全局递增、前 10 名免费名额。"""

    def setUp(self):
        self.user = make_user()

    def _status(self):
        return self.client.get("/api/terminal/reserve/status").json()

    def _reserve(self):
        return self.client.post(
            "/api/terminal/reserve",
            data=json.dumps({}),
            content_type="application/json",
        )

    def test_status_is_public_and_reports_stats(self):
        data = self._status()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["free_quota"], 10)
        self.assertNotIn("me", data)

    def test_reserve_requires_login(self):
        response = self._reserve()
        self.assertEqual(response.status_code, 401)

    def test_reserve_issues_increasing_codes(self):
        self.client.force_login(self.user)
        data = self._reserve().json()
        self.assertEqual(data["code"], "XK-0001")
        self.assertEqual(data["queue_no"], 1)
        self.assertTrue(data["in_free_quota"])

        other = make_user("someone-else")
        self.client.force_login(other)
        data = self._reserve().json()
        self.assertEqual(data["code"], "XK-0002")
        self.assertEqual(data["queue_no"], 2)
        self.assertTrue(data["in_free_quota"])
        self.assertEqual(data["total"], 2)

        # 超出名额后不再标记免费资格。
        beyond = HardwareReservation.objects.create(
            user=make_user("late-comer"), queue_no=11, code="XK-0011"
        )
        self.client.force_login(beyond.user)
        self.assertFalse(self._reserve().json()["in_free_quota"])

    def test_reserve_is_idempotent(self):
        self.client.force_login(self.user)
        first = self._reserve().json()
        second = self._reserve().json()
        self.assertTrue(second["already"])
        self.assertEqual(first["code"], second["code"])
        self.assertEqual(HardwareReservation.objects.count(), 1)

    def test_reserve_sends_notification_with_top10_hint(self):
        self.client.force_login(self.user)
        self._reserve()
        notice = Notification.objects.filter(recipient=self.user).latest("id")
        self.assertIn("XK-0001", notice.body)
        self.assertIn("前 10 名", notice.body)

    def test_cancel_then_reserve_keeps_same_code(self):
        self.client.force_login(self.user)
        first = self._reserve().json()
        response = self.client.post(
            "/api/terminal/reserve/cancel",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        again = self._reserve().json()
        self.assertEqual(again["code"], first["code"])
        self.assertEqual(again["queue_no"], first["queue_no"])
        # 取消的号不给别人占位：下一个预约的人继续往后排。
        other = make_user("someone-else")
        self.client.force_login(other)
        self.assertEqual(self._reserve().json()["queue_no"], 2)

    def test_cancel_without_reservation_404(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/terminal/reserve/cancel",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
