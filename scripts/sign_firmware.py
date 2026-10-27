#!/usr/bin/env python3
"""固件签名：让板子只认自己人签的包。

为什么非要这一层：现在 OTA 只校验 MD5，而 MD5 就在 manifest 里一起下发。
谁能在链路上改 bin，就能顺手把 manifest 里的 MD5 改成新包的摘要——校验永远
「通过」，因为证明和结论来自同一个不可信的来源。签名把这件事拆开：
私钥在你手里，公钥烧在板子里，链路上的人改不了任何一个字节。

链路：

    bin --sha256--> digest --ECDSA(P-256, 私钥)--> sig(70~72B, DER)
                                                       │
    板子: 边下载边算 sha256，收完用内嵌公钥验 sig ──┘ 通过才 Update.end()

设计上的几个决定：

1. **签的是摘要，不是整包**。ECDSA 本来就是「对摘要签名」，签名长度固定，
   不会因为 bin 变成 1.3MB 就变大。
2. **DER 编码**。mbedtls 的 ``mbedtls_pk_verify`` 收 DER；(r,s) 裸拼接是
   OpenSSL 的另一种习惯，混用只会得到一个 ERR_ECP_BAD_INPUT 调半天。
3. **私钥永远不进仓库**。``secrets/`` 已被 .gitignore 忽略。丢了私钥的后果
   写在这里：**以后所有升级只能拔线烧**——OTA 会一律拒绝。
4. **公钥指纹两边对得上**。脚本从公钥 DER 算 SHA-256，板子也从它自己内嵌的
   DER 算同一个值，串口 ``v`` 会打出来。这一步是唯一能证明「我烧进板子的
   公钥，就是这把私钥的公钥」的手段。

用法::

    python scripts/sign_firmware.py keygen          # 一次性：生成密钥 + 写入公钥头
    python scripts/sign_firmware.py sign uploads/firmware/kflow_terminal-0.10.0.bin
    python scripts/sign_firmware.py verify <bin>    # 本地核对边车签名
    python scripts/sign_firmware.py selftest        # 生成板子端自检向量
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "secrets"
KEY_PATH = SECRETS / "ota_signing_key.pem"
PUB_PEM_PATH = SECRETS / "ota_pubkey.pem"
PUB_HEADER = ROOT / "firmware" / "kflow_terminal" / "ota_pubkey.h"
SELFTEST_HEADER = ROOT / "firmware" / "kflow_terminal" / "ota_selftest.h"
DIST_DIR = ROOT / "uploads" / "firmware"

NAME_PATTERN = re.compile(r"^kflow_terminal-(\d+\.\d+\.\d+)\.bin$")

# 板子端自检用的固定串。它必须短、稳定、和真固件无关——
# 自检要回答的是「验签代码和公钥能不能用」，不是「这个 bin 好不好」。
SELFTEST_MESSAGE = b"KFLOW-OTA-SELFTEST-V1"


# ---------------------------------------------------------------- 密钥

def _load_private() -> ec.EllipticCurvePrivateKey:
    if not KEY_PATH.exists():
        raise SystemExit(
            f"找不到私钥 {KEY_PATH}\n先跑一次: python scripts/sign_firmware.py keygen"
        )
    key = serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise SystemExit("私钥不是 EC 私钥，OTP 只能用 P-256")
    return key


def _spki_der(key) -> bytes:
    """SubjectPublicKeyInfo DER。板子端 mbedtls_pk_parse_public_key 直接吃它。"""
    return key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _fingerprint(der: bytes) -> str:
    """公钥指纹：SHA-256(SPKI DER)。

    刻意不用证书指纹：证书 90 天换一次，换完指纹就变了；公钥换了才叫真事。
    """
    return hashlib.sha256(der).hexdigest()


def _digest(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


def _sign_digest(key: ec.EllipticCurvePrivateKey, digest: bytes) -> bytes:
    return key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))


def _verify_digest(pub, digest: bytes, sig: bytes) -> bool:
    try:
        pub.verify(sig, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return True
    except InvalidSignature:
        return False


# ---------------------------------------------------------------- C 头

def _c_array(data: bytes, indent: str = "    ", per_line: int = 12) -> str:
    lines = []
    for start in range(0, len(data), per_line):
        chunk = data[start : start + per_line]
        lines.append(indent + ", ".join(f"0x{byte:02X}" for byte in chunk) + ",")
    return "\n".join(lines)


PUBKEY_TEMPLATE = """\
// 自动生成，勿手改。由 scripts/sign_firmware.py keygen 产出。
//
// 这是 OTA 验签用的公钥（P-256 的 SubjectPublicKeyInfo DER，{length} 字节）。
// 公钥可以公开：它只能证明「这个包是私钥持有者签的」，不能用来签新包。
// 私钥在 secrets/ota_signing_key.pem，不在仓库里。
//
// 指纹（SHA-256 of SPKI DER，板子串口 v 会打同一个值）：
//   {fingerprint}
#pragma once

#include <stdint.h>

static const uint8_t OTA_PUBKEY_DER[] = {{
{body}
}};
static const uint32_t OTA_PUBKEY_DER_LEN = {length};

// 板子自己也算不出这个值时，至少能把前 16 个 hex 打出来跟脚本比对。
static const char OTA_PUBKEY_FP16[] = "{fp16}";
"""

SELFTEST_TEMPLATE = """\
// 自动生成，勿手改。由 scripts/sign_firmware.py selftest 产出。
//
// 板子端验签自检向量：对固定字符串 "{message}" 的 SHA-256 签名。
// 串口发 v 会跑两条断言：
//   1. 用内嵌公钥验这个签名 → 必须通过（证明公钥、mbedtls 通路、DER 编码都对）
//   2. 把摘要翻一个比特再验 → 必须失败（证明它不是「永远返回 ok」的空壳）
// 两条都过才算验签能信。只跑第 1 条的话，一个 return 0 的桩函数也能全绿。
#pragma once

#include <stdint.h>

static const char OTA_SELFTEST_MSG[] = "{message}";
static const uint8_t OTA_SELFTEST_DIGEST[32] = {{
{digest}
}};
static const uint8_t OTA_SELFTEST_SIG[] = {{
{sig}
}};
static const uint32_t OTA_SELFTEST_SIG_LEN = {sig_len};
"""


def _write_pubkey_header(der: bytes) -> None:
    text = PUBKEY_TEMPLATE.format(
        length=len(der),
        fingerprint=_fingerprint(der),
        fp16=_fingerprint(der)[:16],
        body=_c_array(der, indent="    "),
    )
    PUB_HEADER.write_text(text)


def _write_selftest_header(key: ec.EllipticCurvePrivateKey) -> None:
    digest = _digest(SELFTEST_MESSAGE)
    sig = _sign_digest(key, digest)
    text = SELFTEST_TEMPLATE.format(
        message=SELFTEST_MESSAGE.decode(),
        digest=_c_array(digest, indent="    "),
        sig=_c_array(sig, indent="    "),
        sig_len=len(sig),
    )
    SELFTEST_HEADER.write_text(text)


# ---------------------------------------------------------------- 子命令

def cmd_keygen(args) -> int:
    if KEY_PATH.exists() and not args.force:
        print(f"私钥已存在，没动它: {KEY_PATH}")
        print("真要换密钥（注意：换完必须插线重烧一次，老固件不认新公钥），加 --force")
        return 1

    SECRETS.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SECRETS, 0o700)
    except OSError:
        pass

    key = ec.generate_private_key(ec.SECP256R1())
    KEY_PATH.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(KEY_PATH, 0o600)
    PUB_PEM_PATH.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    der = _spki_der(key.public_key())
    _write_pubkey_header(der)
    _write_selftest_header(key)

    print(f"私钥   {KEY_PATH}  (600, 别提交、别丢)")
    print(f"公钥   {PUB_PEM_PATH}")
    print(f"固件头 {PUB_HEADER.relative_to(ROOT)}")
    print(f"自检头 {SELFTEST_HEADER.relative_to(ROOT)}")
    print(f"指纹   {_fingerprint(der)}")
    print()
    print("下一步：编固件 → sign → 上传 bin 与 .sig。首次必须插线烧，因为现在的固件还不验签。")
    return 0


def cmd_sign(args) -> int:
    key = _load_private()
    targets = []
    for raw in args.paths:
        path = Path(raw)
        if not path.exists():
            print(f"跳过（不存在）: {path}")
            continue
        targets.append(path)
    if not targets:
        raise SystemExit("没有可签的文件")

    for path in targets:
        payload = path.read_bytes()
        digest = _digest(payload)
        sig = _sign_digest(key, digest)
        sig_path = path.with_suffix(".sig")
        sig_path.write_text(base64.b64encode(sig).decode() + "\n")
        match = NAME_PATTERN.match(path.name)
        version = match.group(1) if match else "?"
        print(f"{path.name}  version={version}  size={len(payload)}")
        print(f"  sha256={digest.hex()}")
        print(f"  sig={sig_path.name}  {len(sig)}B  base64={base64.b64encode(sig).decode()}")
    return 0


def cmd_verify(args) -> int:
    key = _load_private()
    pub = key.public_key()
    ok = True
    for raw in args.paths:
        path = Path(raw)
        sig_path = path.with_suffix(".sig")
        if not sig_path.exists():
            print(f"{path.name}: 缺边车 {sig_path.name}")
            ok = False
            continue
        sig = base64.b64decode(sig_path.read_text().strip())
        digest = _digest(path.read_bytes())
        good = _verify_digest(pub, digest, sig)
        print(f"{path.name}: {'ok' if good else 'BAD'}  sig={len(sig)}B  sha256={digest.hex()[:16]}...")
        ok = ok and good
    return 0 if ok else 1


def cmd_pubkey(args) -> int:
    key = _load_private()
    der = _spki_der(key.public_key())
    _write_pubkey_header(der)
    _write_selftest_header(key)
    print(f"公钥头已重写，指纹 {_fingerprint(der)}")
    return 0


def cmd_selftest(args) -> int:
    key = _load_private()
    _write_selftest_header(key)
    print(f"自检向量已重写: {SELFTEST_HEADER.relative_to(ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KFlow 固件签名工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_keygen = sub.add_parser("keygen", help="生成 P-256 密钥并写公钥头")
    p_keygen.add_argument("--force", action="store_true", help="覆盖已有私钥（会断掉 OTA）")
    p_keygen.set_defaults(func=cmd_keygen)

    p_sign = sub.add_parser("sign", help="给 bin 签名，产出同名 .sig")
    p_sign.add_argument("paths", nargs="+")
    p_sign.set_defaults(func=cmd_sign)

    p_verify = sub.add_parser("verify", help="本地核对边车签名")
    p_verify.add_argument("paths", nargs="+")
    p_verify.set_defaults(func=cmd_verify)

    p_pub = sub.add_parser("pubkey", help="只重写公钥头（换了构建机时用）")
    p_pub.set_defaults(func=cmd_pubkey)

    p_self = sub.add_parser("selftest", help="重写板子端自检向量")
    p_self.set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
