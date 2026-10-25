#!/usr/bin/env python3
"""从 PNG 里剥掉指定的 chunk（默认 eXIf），用于让 PNG 符合 IconServices 的白名单。

为什么用「剥离」而不是「重新编码」：
    CoreGraphics 重写 PNG 时会把源图的 metadata 一并带过去，eXIf 去不掉。
    而 PNG 的 CRC32 是逐 chunk 独立计算的，删掉整个 chunk 不影响
    其它 chunk 的 CRC，所以直接跳过这个 chunk 写出去就是合法 PNG。

为什么必须去掉 eXIf：
    macOS IconServices（Dock/Launchpad/Finder 用的 icns 解析器）对 icns 内嵌
    PNG 的 chunk 组合有白名单，遇到 eXIf 会判定 PNG 非法 → 整张 icns 被拒 →
    回退到「通用应用占位图标」。ImageIO 宽容，所以「ImageIO 能读」≠「系统能显示」。

用法：
    python scripts/build/strip_png_chunks.py assets/AppIcon.iconset          # 处理整目录
    python scripts/build/strip_png_chunks.py <file.png> [...]                # 处理指定文件
"""
import os
import struct
import sys
import zlib

STRIP = {b"eXIf", b"eXIf", b"tIME", b"zTXt", b"iTXt"}


def strip_chunks(path):
    d = open(path, "rb").read()
    if d[:4] != b"\x89PNG":
        return None
    sig = d[:8]
    pos = 8
    out = [sig]
    removed = []
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]
        ct = d[pos + 4:pos + 8]
        data = d[pos + 8:pos + 8 + ln]
        # chunk 完整长度 = 4(len) + 4(type) + ln(data) + 4(CRC)
        block_len = 12 + ln
        if ct in STRIP:
            removed.append(ct.decode("latin1"))
        else:
            out.append(d[pos:pos + block_len])
        pos += block_len
        if ct == b"IEND":
            break
    if not removed:
        return []
    with open(path, "wb") as f:
        f.write(b"".join(out))
    return removed


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    targets = []
    for a in args:
        if os.path.isdir(a):
            targets += [os.path.join(a, f) for f in sorted(os.listdir(a))
                        if f.lower().endswith(".png")]
        else:
            targets.append(a)
    for p in targets:
        r = strip_chunks(p)
        name = os.path.basename(p)
        if r is None:
            print(f"  ? {name:24s} 不是 PNG")
        elif r:
            print(f"  ✓ {name:24s} 已剥离 {r}")
        else:
            print(f"  · {name:24s} 无需剥离")


if __name__ == "__main__":
    main()
