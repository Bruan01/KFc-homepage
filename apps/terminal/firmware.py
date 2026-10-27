"""固件分发：让设备自己检查、自己下载、自己换掉自己。

为什么要有这一层：板子摆在桌上，每改一版就要拔线、杀串口占用、compile、
upload、等十几秒重启，一轮三到五分钟。把它变成一个 HTTP 接口之后，同一块
板子只在上电那次插过线，之后所有版本都是无线的。

分发目录的约定很硬：只认 ``kflow_terminal-<主>.<次>.<补丁>.bin`` 这一个形状。
不解析任何用户传来的路径——查版本时是在扫到的清单里做字典查找，字符串根本
拼不进文件系统路径，目录穿越在这里没有落点。

签名（v0.10.0 起）：每个 bin 旁边可以有一个同名 ``.sig`` 边车文件，内容是
``base64(DER)`` 的 ECDSA P-256 签名，签的是整包的 SHA-256。设备端用编译进去
的公钥验，验不过一个字节都不写。

**为什么边车文件而不是塞进 bin 尾巴**：bin 的字节必须和设备写进 flash 的字节
完全一致，esp_ota_write 会校验镜像头；在尾巴上加东西就得让设备知道到哪里为止，
而"到哪里为止"又得从不可信的清单里读——绕一圈回到原点。
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

# 文件名就是版本号，避免「目录里哪个才是最新的」这种要读文件才能回答的问题。
NAME_PATTERN = re.compile(r"^kflow_terminal-(\d+)\.(\d+)\.(\d+)\.bin$")

# 一次 OTA 的合法上限。真正拦住的不是这里，而是 Update.begin() 拿分区容量比对；
# 这条只是不让一个被篡改的清单把设备拖进几个 G 的下载里。
MAX_BUILD_BYTES = 8 * 1024 * 1024

# (路径, mtime, 大小) -> (md5, sha256)
_DIGEST_CACHE: dict[tuple[str, int, int], tuple[str, str]] = {}


def dist_dir() -> Path:
    """bin 存放目录。默认 uploads/firmware，可用 settings 覆盖。"""
    configured = getattr(settings, "TERMINAL_FIRMWARE_DIR", None)
    if configured:
        return Path(configured)
    return Path(settings.MEDIA_ROOT) / "firmware"


def signature_required() -> bool:
    """没有签名的包要不要发出去。

    默认 True：设备从 v0.10.0 起只认签名包，把未签名包列进清单的后果是
    「有更新但永远升不了」——比明确说「没得升」更难查。默认拒绝，
    至少 `reason` 会把原因写清楚。
    """
    return bool(getattr(settings, "TERMINAL_FIRMWARE_REQUIRE_SIG", True))


@dataclass(frozen=True)
class Build:
    version: str
    path: Path
    size: int
    md5: str
    sha256: str
    built_at: float
    sig: str = ""        # base64(DER)，空串 = 没签名
    sig_error: str = ""  # 非空 = 签名不可用（原因写在里面）

    @property
    def md5_hex(self) -> str:
        return self.md5

    @property
    def signed(self) -> bool:
        """能不能拿去推给设备。

        注意这只回答「签名可用」，不回答「该不该推」——后者看版本比较。
        """
        return bool(self.sig) and not self.sig_error

    def as_dict(self) -> dict:
        from datetime import datetime, timezone as dt_timezone

        from django.utils import timezone as tz

        moment = datetime.fromtimestamp(self.built_at, tz=dt_timezone.utc)
        return {
            "version": self.version,
            "size": self.size,
            "md5": self.md5,
            "sha256": self.sha256,
            "sig": self.sig,
            "signed": self.signed,
            "built_at": tz.localtime(moment).strftime("%Y-%m-%d %H:%M"),
        }


def version_tuple(raw: str) -> tuple[int, int, int]:
    """宽松解析版本号。

    设备上报的版本来自编译期宏，可能是 "0.5.0"、"v0.5.0" 或者干脆是空串
    （老固件没上报过）。解析不了就当成 (0,0,0)——**比抛异常好**：
    调用方要的是「该不该升级」，不是「这个字符串合不合法」。
    """
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", raw or "")
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _digest_of(path: Path) -> tuple[str, str]:
    """按 (路径, mtime, 大小) 缓存摘要，返回 (md5, sha256)。

    编译一次 bin 反复下载几十次，每次都读 1.2MB 算摘要纯属浪费；
    但只要文件被覆盖，mtime 必变，缓存自然失效，不会拿到旧摘要。
    两个摘要一趟读完：反正都是顺序扫一遍，分两次读等于把 1.2MB 读两遍。
    """
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _DIGEST_CACHE.get(key)
    if cached:
        return cached
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(256 * 1024), b""):
            md5.update(chunk)
            sha256.update(chunk)
    value = (md5.hexdigest(), sha256.hexdigest())
    _DIGEST_CACHE[key] = value
    return value


def sig_path_for(bin_path: Path) -> Path:
    """边车签名路径：``kflow_terminal-1.2.3.bin`` → ``kflow_terminal-1.2.3.sig``。"""
    return bin_path.with_suffix(".sig")


def _load_sig(bin_path: Path) -> tuple[str, str]:
    """读边车签名并校验它和这个 bin 对不对得上。

    返回 (base64 签名, 错误说明)。没有边车文件不算错误——那只是"这个包没签名"，
    由调用方决定要不要发。边车存在但内容坏掉才是错误：那说明复制过程出了问题，
    这种包推给设备只会白白触发一次验签失败。

    为什么服务端也要验一遍：设备验签失败只会留一行串口日志，而它可能不在你手边。
    在这里先验，发布时就能发现问题——签名是给人看的第二双眼睛，不是重复劳动。
    """
    sig_file = sig_path_for(bin_path)
    if not sig_file.exists():
        return "", ""
    try:
        raw = sig_file.read_text().strip()
    except OSError as exc:
        return "", f"cannot read sig: {exc}"

    try:
        # validate=True：base64 里混进换行/空格以外的东西就直接报错，
        # 而不是静默丢掉非法字符后拼出一个「看起来能解」的签名。
        base64.b64decode(raw, validate=True)
    except Exception:
        return "", "sig is not valid base64"

    problem = verify_signature(bin_path, raw)
    return raw, problem


def _public_key():
    """读验签公钥。拿不到就返回 None（表示"没法验"，不是"验失败"）。

    默认找 ``secrets/ota_pubkey.pem``——和签名脚本同一个目录，但只有公钥。
    生产机上不一定要有：没有就跳过服务端验证，设备端仍然是最终裁判。
    """
    configured = getattr(settings, "TERMINAL_FIRMWARE_PUBKEY", None)
    if configured:
        candidate = Path(configured)
    else:
        base = Path(getattr(settings, "BASE_DIR", Path.cwd()))
        candidate = base / "secrets" / "ota_pubkey.pem"
    if not candidate.is_file():
        return None

    from cryptography.hazmat.primitives import serialization

    try:
        return serialization.load_pem_public_key(candidate.read_bytes())
    except Exception:
        return None


def verify_signature(bin_path: Path, sig_b64: str) -> str:
    """核对一个 bin 的边车签名。返回错误说明，空串表示通过（或无从核对）。"""
    key = _public_key()
    if key is None:
        return ""

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    _, sha256_hex = _digest_of(bin_path)
    try:
        sig = base64.b64decode(sig_b64, validate=True)
        key.verify(
            sig,
            bytes.fromhex(sha256_hex),
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
    except InvalidSignature:
        return "signature does not match this bin"
    except Exception as exc:  # 公钥算法不对、签名长度不对等
        return f"signature unusable: {exc}"
    return ""


def published() -> list[Build]:
    """目录里所有可用构建，版本高的在前。扫不到目录就返回空表，不报错。"""
    root = dist_dir()
    if not root.is_dir():
        return []

    builds: list[Build] = []
    for entry in root.iterdir():
        match = NAME_PATTERN.match(entry.name)
        if not match or not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            # 正在被覆盖/删除的文件直接跳过，不要因为一个半成品让整个清单失败。
            continue
        if stat.st_size <= 0 or stat.st_size > MAX_BUILD_BYTES:
            continue
        md5, sha256 = _digest_of(entry)
        sig, sig_error = _load_sig(entry)
        builds.append(
            Build(
                version=".".join(match.groups()),
                path=entry,
                size=stat.st_size,
                md5=md5,
                sha256=sha256,
                sig=sig,
                sig_error=sig_error,
                built_at=stat.st_mtime,
            )
        )
    builds.sort(key=lambda item: version_tuple(item.version), reverse=True)
    return builds


def latest_build() -> Build | None:
    builds = published()
    return builds[0] if builds else None


def build_for(version: str) -> Build | None:
    """按版本号精确取一个构建。只做字典查找，不拼路径。"""
    wanted = (version or "").strip()
    if not wanted:
        return None
    for build in published():
        if build.version == wanted:
            return build
    return None


def update_plan(current: str) -> dict:
    """给设备的答案：要不要升、升到哪个、多大、签名是什么。

    判断放在服务端而不是固件里，是因为版本语义只能有一处实现。固件只管
    「服务端说升我就升」，将来换成灰度、按设备分组、强制降级都只改这里。
    """
    latest = latest_build()
    if latest is None:
        return {
            "update_available": False,
            "reason": "no build published",
            "current": current,
        }

    # 签名不可用的最新包：明确说不升，并把原因写清楚。
    # 这里刻意不往后找"上一个有签名的版本"——那会把设备悄悄钉在一个旧版本上，
    # 而你以为它在跟进最新。发布流程出错就该在清单里显形。
    if not latest.signed and signature_required():
        detail = latest.sig_error or "no .sig next to the bin"
        return {
            "update_available": False,
            "reason": f"latest build {latest.version} is not usable: {detail}",
            "current": current,
            "latest": latest.version,
            **latest.as_dict(),
        }

    has_newer = version_tuple(latest.version) > version_tuple(current)
    plan = {
        "update_available": has_newer,
        "current": current,
        "latest": latest.version,
        **latest.as_dict(),
    }
    if has_newer:
        plan["url"] = f"/api/terminal/firmware/download?version={latest.version}"
    else:
        plan["reason"] = "already up to date"
    return plan


def save_upload(source, filename: str) -> Build:
    """把编译产物收进分发目录。

    不是给设备用的——设备只读。这是给部署脚本/管理页用的入口，文件名必须
    符合约定，否则宁可拒收：一个不符合命名规则的文件进目录后不会被任何
    查询命中，只会在那里烂掉。
    """
    name = os.path.basename(filename or "")
    if not NAME_PATTERN.match(name):
        raise ValueError("bin 文件名必须是 kflow_terminal-<ver>.bin")

    root = dist_dir()
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    tmp = target.with_suffix(".bin.part")
    size = 0
    with tmp.open("wb") as handle:
        for chunk in iter(lambda: source.read(256 * 1024), b""):
            size += len(chunk)
            if size > MAX_BUILD_BYTES:
                handle.close()
                tmp.unlink(missing_ok=True)
                raise ValueError("固件超过体积上限")
            handle.write(chunk)
    tmp.replace(target)

    stat = target.stat()
    md5, sha256 = _digest_of(target)
    sig, sig_error = _load_sig(target)
    return Build(
        version=".".join(NAME_PATTERN.match(name).groups()),
        path=target,
        size=stat.st_size,
        md5=md5,
        sha256=sha256,
        sig=sig,
        sig_error=sig_error,
        built_at=stat.st_mtime,
    )
