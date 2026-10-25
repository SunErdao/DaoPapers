#!/usr/bin/env python3
"""从 assets/AppIcon.icns 里提取指定图层的 PNG，并 base64 内嵌到 ui/index.html。

为什么这么做（2026-10-25）：
    窗口左上角的品牌标记原本是一个手写的通用占位图形（蓝圆+两条横线），
    跟应用图标毫无关系——用户看到「窗口里的图标还是旧的」就是这个。
    要让它和应用图标**像素级一致**，唯一可靠的做法是直接用 AppIcon.icns
    里的像素，而不是再手绘一版近似图形（近似=迟早走样）。

    这里取 128×128 的 ic07 图层：
      · 128px 在 @2x 屏上以 28 逻辑点显示 = 56 物理像素，绰绰有余
      · 体积可控（base64 约 24KB），base64 内嵌后不依赖任何外部文件，
        也就不会因为「打包时漏带资源」而失效
"""

from __future__ import annotations

import base64
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICNS = os.path.join(ROOT, "assets", "AppIcon.icns")
INDEX = os.path.join(ROOT, "ui", "index.html")

# icns 图层类型 → 该层的像素尺寸
LAYER_PX = {
    b"ic07": 128,
    b"ic08": 256,
    b"ic13": 256,   # 256@2x
    b"ic09": 512,
    b"ic14": 512,   # 512@2x
    b"ic10": 1024,
    b"ic11": 32,
    b"ic12": 64,
}


def extract(icns_path: str, want_px: int = 128) -> bytes:
    """按像素尺寸从 icns 里取一层 PNG 原始字节。"""
    with open(icns_path, "rb") as fp:
        data = fp.read()
    if data[:4] != b"icns":
        raise SystemExit(f"不是 icns 文件：{icns_path}")
    total = struct.unpack(">I", data[4:8])[0]
    if total != len(data):
        print(f"  ! 头部声明长度 {total} 与实际 {len(data)} 不一致，继续按实际解析")

    off = 8
    found: dict[int, bytes] = {}
    while off + 8 <= len(data):
        ctype = data[off:off + 4]
        clen = struct.unpack(">I", data[off + 4:off + 8])[0]
        if clen < 8:
            raise SystemExit(f"chunk 长度非法：{ctype!r} len={clen}")
        body = data[off + 8:off + clen]
        if ctype in LAYER_PX and body[:4] == b"\x89PNG":
            px = LAYER_PX[ctype]
            found.setdefault(px, body)
        off += clen  # 步进 = 长度字段本身（含 8 字节头）

    if want_px not in found:
        raise SystemExit(f"icns 里没有 {want_px}px 的 PNG 图层，可用：{sorted(found)}")
    return found[want_px]


def main() -> int:
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 128
    png = extract(ICNS, want)
    b64 = base64.b64encode(png).decode("ascii")
    print(f"提取 {want}px 图层：{len(png):,} 字节 → base64 {len(b64):,} 字符")

    with open(INDEX, "r", encoding="utf-8") as fp:
        html = fp.read()

    marker = "brand-mark-img"
    pattern = re.compile(
        r'(<img class="brand-mark-img"[^>]*?src="data:image/png;base64,)([A-Za-z0-9+/=]*)(")',
        re.S,
    )
    if not pattern.search(html):
        raise SystemExit(
            "ui/index.html 里找不到 <img class=\"brand-mark-img\"> 占位，\n"
            "请确认 HTML 结构是否被改动过（占位必须原样保留 src=\"data:image/png;base64,\"）。"
        )
    html = pattern.sub(lambda m: m.group(1) + b64 + m.group(3), html, count=1)

    with open(INDEX, "w", encoding="utf-8") as fp:
        fp.write(html)
    print(f"已写入 {INDEX}（{marker}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
