#!/usr/bin/env python3
"""把一组根证书拼成固件里的一个 C 字符串。

为什么是「一组」而不是「一张」：钉一张根证书等于把设备的可用性绑在那家 CA 的
经营策略上。mg.kfc-linlin.top 现在挂在 Cloudflare 后面，链是
leaf → GTS WE1 → GTS Root R4。Cloudflare 换过 CA（DigiCert → Let's Encrypt
→ Google Trust Services），换的那天如果板子只认旧根，症状是「WiFi 好、
https 全挂、OTA 永远升不了」——而那时候已经没法用 OTA 修它了。

所以认三张根：GTS R4、GTS R1、ISRG X1。它们覆盖 Cloudflare 现在和可预见的
将来会用到的链。代价是信任面从「一家」变成「三家」，这是刻意的取舍：
对一个摆在桌上的桌面终端来说，可用性比极限的信任收敛更值钱。

用法::

    python scripts/gen_tls_roots.py /tmp/GTS_Root_R4.pem /tmp/GTS_Root_R1.pem \\
        /tmp/ISRG_Root_X1.pem -o firmware/kflow_terminal/tls_roots.h

证书从哪儿来：macOS 系统库里有全套 Mozilla 根，离线可取——
``security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain``
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

HEADER = """\
// 自动生成，勿手改。由 scripts/gen_tls_roots.py 产出。
//
// 固件信任的根证书集合，用 mbedtls 的 setCACert 一次喂进去。
// mbedtls_x509_crt_parse 支持多张 PEM 拼接，所以这里是一个长字符串，
// 不是数组——setCACert 只收一个以 NUL 结尾的 buffer。
//
// 为什么不止一张：钉死单张根证书的那天，CA 一换，板子就再也升不了级，
// 而修它只能拔线。三张覆盖 Cloudflare 现在和近期会用到的链。
//
{listing}
//
// 换根证书的流程：改这里 → 编新固件 → 签名 → 发布。**先用串口 v 和 o
// 在板上验证一遍再推**，别让一台设备成为「新根不对」的第一个受害者。
#pragma once

static const char KFLOW_ROOT_CA_PEM[] =
{body};
"""


def load(path: Path) -> tuple[x509.Certificate, str]:
    pem = path.read_bytes()
    cert = x509.load_pem_x509_certificate(pem)
    # 统一成单张、行宽 64 的规范 PEM：输入里夹带的注释、多余空行会被清掉，
    # 避免 mbedtls 在奇怪的位置解析失败（它对 PEM 头前面的垃圾不总是宽容）。
    normalized = cert.public_bytes(serialization.Encoding.PEM).decode()
    return cert, normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 tls_roots.h")
    parser.add_argument("pems", nargs="+")
    parser.add_argument(
        "-o",
        "--output",
        default="firmware/kflow_terminal/tls_roots.h",
        help="输出路径（相对仓库根或绝对路径）",
    )
    args = parser.parse_args(argv)

    blocks: list[str] = []
    listing: list[str] = []
    for raw in args.pems:
        path = Path(raw)
        cert, pem = load(path)
        subject = cert.subject.rfc4514_string()
        fp = hashlib.sha256(
            cert.public_bytes(serialization.Encoding.DER)
        ).hexdigest()
        not_after = cert.not_valid_after_utc.strftime("%Y-%m-%d")
        comment = f"//   {subject}\n//     sha256={fp}\n//     expires={not_after}"
        listing.append(comment)
        lines = [f'    "{line}\\n"' for line in pem.strip().splitlines()]
        blocks.append("\n".join(lines))

    body = "\n\n".join(blocks)
    text = HEADER.format(listing="\n".join(listing), body=body)

    out = Path(args.output)
    if not out.is_absolute():
        out = Path(__file__).resolve().parent.parent / out
    out.write_text(text)
    print(f"{out}  {len(blocks)} 张根证书, {len(text)} 字节源码")
    for line in listing:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
