"""固件分发：让设备自己检查、自己下载、自己换掉自己。

为什么要有这一层：板子摆在桌上，每改一版就要拔线、杀串口占用、compile、
upload、等十几秒重启，一轮三到五分钟。把它变成一个 HTTP 接口之后，同一块
板子只在上电那次插过线，之后所有版本都是无线的。

分发目录的约定很硬：只认 ``kflow_terminal-<主>.<次>.<补丁>.bin`` 这一个形状。
不解析任何用户传来的路径——查版本时是在扫到的清单里做字典查找，字符串根本
拼不进文件系统路径，目录穿越在这里没有落点。
"""
from __future__ import annotations

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

_MD5_CACHE: dict[tuple[str, int, int], str] = {}


def dist_dir() -> Path:
    """bin 存放目录。默认 uploads/firmware，可用 settings 覆盖。"""
    configured = getattr(settings, "TERMINAL_FIRMWARE_DIR", None)
    if configured:
        return Path(configured)
    return Path(settings.MEDIA_ROOT) / "firmware"


@dataclass(frozen=True)
class Build:
    version: str
    path: Path
    size: int
    md5: str
    built_at: float

    @property
    def md5_hex(self) -> str:
        return self.md5

    def as_dict(self) -> dict:
        from datetime import datetime, timezone as dt_timezone

        from django.utils import timezone as tz

        moment = datetime.fromtimestamp(self.built_at, tz=dt_timezone.utc)
        return {
            "version": self.version,
            "size": self.size,
            "md5": self.md5,
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


def _md5_of(path: Path) -> str:
    """按 (路径, mtime, 大小) 缓存摘要。

    编译一次 bin 反复下载几十次，每次都读 1.2MB 算摘要纯属浪费；
    但只要文件被覆盖，mtime 必变，缓存自然失效，不会拿到旧摘要。
    """
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _MD5_CACHE.get(key)
    if cached:
        return cached
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(256 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _MD5_CACHE[key] = value
    return value


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
        builds.append(
            Build(
                version=".".join(match.groups()),
                path=entry,
                size=stat.st_size,
                md5=_md5_of(entry),
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
    """给设备的答案：要不要升、升到哪个、多大、摘要是什么。

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
    return Build(
        version=".".join(NAME_PATTERN.match(name).groups()),
        path=target,
        size=stat.st_size,
        md5=_md5_of(target),
        built_at=stat.st_mtime,
    )
