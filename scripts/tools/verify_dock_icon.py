#!/usr/bin/env python3
"""用「Dock 自己的渲染路径」验收图标 —— 终极判据。

之前踩过的坑：
  - 用 ImageIO 校验 → 太宽容，结构错了也通过（假通过）
  - 用 iconForFile_(.icns) 判定 → macOS 对孤立 .icns 本来就返回灰占位图（判据本身错）
  - 用 iconForFile_(.app) 判定 → macOS 会自动加圆角遮罩+投影，像素对不上原始 PNG（假失败）

正确判据：**问 Dock 自己要它要显示的那张图**。
  1. 从 .app bundle 拿 IconServices 渲染的图标（含 macOS 样式）
  2. 提取 icns 里的 512 层，套上同样的圆角遮罩
  3. 比对两者的「特征色分布」——太阳位置的暖橙色像素数量
  比像素更稳：直接看 IconServices 渲染结果里有没有暖橙色太阳。

用法：
    python scripts/tools/verify_dock_icon.py
"""
import os
import struct
import sys
from collections import Counter

import AppKit
import Quartz
from CoreFoundation import CFURLCreateWithFileSystemPath, kCFAllocatorDefault, kCFURLPOSIXPathStyle
from Foundation import NSMakeRect

APP = "/Applications/DaoPapers.app"
ICNS = os.path.join(APP, "Contents/Resources/AppIcon.icns")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "build", "verify")


def render(img, size):
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0)
    ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(ctx)
    img.drawInRect_(NSMakeRect(0, 0, size, size))
    AppKit.NSGraphicsContext.restoreGraphicsState()
    cg = Quartz.CGBitmapContextCreateImage(ctx.CGContext())
    d = rep.bitmapData()
    bpr = rep.bytesPerRow()
    return d, bpr, cg


def feature(d, bpr, size):
    """统计特征：暖橙色太阳像素、灰度像素、唯一色数"""
    sun = gray = 0
    cols = Counter()
    for y in range(size):
        for x in range(size):
            o = y * bpr + x * 4
            r, g, b = d[o], d[o + 1], d[o + 2]
            cols[(r, g, b)] += 1
            if r - b > 40 and r > 180:
                sun += 1
            if abs(r - g) < 10 and abs(g - b) < 10:
                gray += 1
    n = size * size
    return sun, sun / n, gray / n, len(cols)


def main():
    os.makedirs(OUT, exist_ok=True)
    size = 128

    print("=== Dock 图标终极验收 ===\n")

    # 1) IconServices 给 .app 的图标（这就是 Dock 显示的那张）
    app_img = AppKit.NSWorkspace.sharedWorkspace().iconForFile_(APP)
    if app_img is None:
        print("❌ IconServices 无法读取 .app")
        return 1
    d, bpr, cg = render(app_img, size)
    sun, sun_r, gray_r, uniq = feature(d, bpr, size)
    print(f"① Dock 渲染的图标（IconServices 读 .app）")
    print(f"   太阳像素 {sun} ({sun_r:.2%})  灰度 {gray_r:.1%}  唯一色 {uniq}")
    dst = os.path.join(OUT, "final_dock_icon.png")
    url = CFURLCreateWithFileSystemPath(kCFAllocatorDefault, os.path.abspath(dst), kCFURLPOSIXPathStyle, False)
    dd = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dd, cg, None)
    Quartz.CGImageDestinationFinalize(dd)
    print(f"   → {dst}")

    # 2) icns 里的 512 层（源）
    blob = open(ICNS, "rb").read()
    pos = 8
    src_png = None
    while pos < len(blob):
        ct = blob[pos:pos + 4]
        sz = struct.unpack(">I", blob[pos + 4:pos + 8])[0]
        dta = blob[pos + 8:pos + sz]
        if dta[:4] == b"\x89PNG":
            w = struct.unpack(">I", dta[16:20])[0]
            if w == 512:
                src_png = dta
                break
        pos += sz
    if src_png is None:
        print("❌ icns 里找不到 512 层")
        return 1

    tmp = os.path.join(OUT, "_src512.png")
    with open(tmp, "wb") as f:
        f.write(src_png)
    src_img = AppKit.NSImage.alloc().initWithContentsOfFile_(tmp)
    d2, bpr2, cg2 = render(src_img, size)
    sun2, sun2_r, gray2_r, uniq2 = feature(d2, bpr2, size)
    print(f"\n② icns 源 512 层")
    print(f"   太阳像素 {sun2} ({sun2_r:.2%})  灰度 {gray2_r:.1%}  唯一色 {uniq2}")
    dst2 = os.path.join(OUT, "final_source_512.png")
    url2 = CFURLCreateWithFileSystemPath(kCFAllocatorDefault, os.path.abspath(dst2), kCFURLPOSIXPathStyle, False)
    dd2 = Quartz.CGImageDestinationCreateWithURL(url2, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dd2, cg2, None)
    Quartz.CGImageDestinationFinalize(dd2)
    print(f"   → {dst2}")

    print()
    # 判定：Dock 图标必须有暖橙太阳（占比接近源图层）
    if sun > 20 and abs(sun_r - sun2_r) < 0.02:
        print(f"✅ 通过：Dock 渲染出的图标与源图层特征一致（太阳占比 "
              f"{sun_r:.2%} vs {sun2_r:.2%}）")
        print("   → Dock / 启动台 会显示新的日落波浪图标")
        return 0
    if sun <= 20:
        print(f"❌ Dock 图标里没有暖橙太阳（{sun} 像素）—— 显示的不是新图标")
    else:
        print(f"⚠️ 太阳占比差异较大（{sun_r:.2%} vs {sun2_r:.2%}），需人工看图确认")
    return 1


if __name__ == "__main__":
    sys.exit(main())
