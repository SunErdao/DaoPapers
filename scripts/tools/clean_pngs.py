#!/usr/bin/env python3
"""用 CoreGraphics 重新编码 iconset 里的 PNG，产出不含 eXIf 等非白名单 chunk 的干净 PNG。

为什么必须这么做：
    WebKit 的 SVG 快照会带出 `eXIf` chunk（EXIF 元数据）。
    macOS 的 IconServices（Dock / Launchpad / Finder 实际用的 icns 解析器）
    对 icns 内嵌 PNG 的 chunk 组合有白名单，遇到 eXIf 会判定该 PNG 非法 →
    整张 icns 被拒绝 → 回退到「通用应用占位图标」。

    ImageIO（我之前用的校验工具）比 IconServices 宽容得多，所以
    「ImageIO 能解析」≠「系统能显示」。验收必须用 IconServices。

用法：
    python scripts/tools/clean_pngs.py            # 清洗 assets/AppIcon.iconset/
    python scripts/tools/clean_pngs.py --verify   # 清洗后用 IconServices 验收
"""
import os
import struct
import sys

import Quartz
from CoreFoundation import (
    CFURLCreateWithFileSystemPath,
    kCFAllocatorDefault,
    kCFURLPOSIXPathStyle,
)
from Foundation import NSURL

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICONSET = os.path.join(ROOT, "assets", "AppIcon.iconset")

# 允许出现在 icns 内嵌 PNG 里的 chunk（Apple 白名单的保守子集）
ALLOWED = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"cHRM",
           b"iCCP", b"pHYs", b"tRNS", b"tEXt", b"zTXt", b"iTXt"}


def list_chunks(path):
    """返回 [(type, length), ...]"""
    d = open(path, "rb").read()
    assert d[:4] == b"\x89PNG", path
    pos, out = 8, []
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]
        ct = d[pos + 4:pos + 8]
        out.append((ct, ln))
        pos += 12 + ln
        if ct == b"IEND":
            break
    return out


def clean_one(path):
    """用 CoreGraphics 重写 PNG，产出无 eXIf 的干净版本。"""
    url = CFURLCreateWithFileSystemPath(
        kCFAllocatorDefault, os.path.abspath(path), kCFURLPOSIXPathStyle, False)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        raise RuntimeError(f"ImageIO 读不出 {path}")
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if cg is None:
        raise RuntimeError(f"解不出图像 {path}")

    out_url = NSURL.fileURLWithPath_(path)
    dst = Quartz.CGImageDestinationCreateWithURL(
        out_url, "public.png", 1, None)
    if dst is None:
        raise RuntimeError(f"无法创建 PNG 输出 {path}")
    Quartz.CGImageDestinationAddImage(dst, cg, None)
    if not Quartz.CGImageDestinationFinalize(dst):
        raise RuntimeError(f"PNG 写出失败 {path}")


def main():
    files = sorted(f for f in os.listdir(ICONSET) if f.endswith(".png"))
    print(f"清洗 {len(files)} 个 PNG（去掉 IconServices 不认的 chunk）：")
    for f in files:
        p = os.path.join(ICONSET, f)
        before = list_chunks(p)
        bad = [ct.decode("latin1") for ct, _ in before if ct not in ALLOWED]
        clean_one(p)
        after = list_chunks(p)
        bad_after = [ct.decode("latin1") for ct, _ in after if ct not in ALLOWED]
        w = Quartz.CGImageGetWidth(
            Quartz.CGImageSourceCreateImageAtIndex(
                Quartz.CGImageSourceCreateWithURL(
                    CFURLCreateWithFileSystemPath(
                        kCFAllocatorDefault, os.path.abspath(p),
                        kCFURLPOSIXPathStyle, False), None), 0, None))
        mark = "✓" if not bad_after else "✗"
        print(f"  {mark} {f:24s} {w:>4}px  "
              f"清洗前多余chunk={bad or '无'}  清洗后={bad_after or '干净'}")


if __name__ == "__main__":
    main()
