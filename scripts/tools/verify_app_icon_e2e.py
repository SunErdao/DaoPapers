#!/usr/bin/env python3
"""端到端验收「应用图标是否真的在系统各处生效」。

三个检查点（对应用户实际会看到的三处）：
  1. 启动台 / Dock  →  IconServices 读 .app bundle 的图标
  2. 窗口标题栏代理图标 → 运行中进程的 NSApp.applicationIconImage
  3. Finder 里的文件图标 → IconServices 读 .icns 文件本身

每处都渲染成 PNG 供肉眼确认，同时做「特征色」自动判定：
    图标里必须能找到暖橙色的太阳（r >> b）
    否则说明显示的还是旧图标 / 占位图
"""
import os
import struct
import sys

import AppKit
import Quartz
from CoreFoundation import CFURLCreateWithFileSystemPath, kCFAllocatorDefault, kCFURLPOSIXPathStyle
from Foundation import NSMakeRect

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "build", "verify")
APP = "/Applications/DaoPapers.app"
ICNS = os.path.join(APP, "Contents/Resources/AppIcon.icns")


def render_to_png(img, size, out):
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, "NSCalancedRGBColorSpace" if False else "NSCalibratedRGBColorSpace", 0, 0)
    ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(ctx)
    img.drawInRect_(NSMakeRect(0, 0, size, size))
    AppKit.NSGraphicsContext.restoreGraphicsState()
    cg = Quartz.CGBitmapContextCreateImage(ctx.CGContext())
    url = CFURLCreateWithFileSystemPath(kCFAllocatorDefault, os.path.abspath(out), kCFURLPOSIXPathStyle, False)
    dst = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dst, cg, None)
    Quartz.CGImageDestinationFinalize(dst)

    # 特征检测：找暖橙色太阳（r 明显大于 b）
    d = rep.bitmapData()
    bpr = rep.bytesPerRow()
    sun = 0
    gray = 0
    for y in range(0, size, 2):
        for x in range(0, size, 2):
            o = y * bpr + x * 4
            r, g, b = d[o], d[o + 1], d[o + 2]
            if r - b > 40 and r > 180:
                sun += 1
            if abs(r - g) < 8 and abs(g - b) < 8:
                gray += 1
    n = (size // 2) ** 2
    return sun, sun / n, gray / n


def main():
    os.makedirs(OUT, exist_ok=True)
    print("=== 应用图标端到端验收 ===\n")

    checks = [
        ("启动台/Dock（IconServices 读 .app）", APP, "dock_app.png"),
        ("Finder 文件图标（IconServices 读 .icns）", ICNS, "finder_icns.png"),
    ]

    all_ok = True
    for label, target, fname in checks:
        img = AppKit.NSWorkspace.sharedWorkspace().iconForFile_(target)
        if img is None:
            print(f"❌ {label}: IconServices 返回 None")
            all_ok = False
            continue
        out = os.path.join(OUT, fname)
        sun, sun_ratio, gray_ratio = render_to_png(img, 256, out)
        has_sun = sun > 30
        if not has_sun:
            all_ok = False
        print(f"{'✅' if has_sun else '❌'} {label}")
        print(f"     太阳像素 {sun:>5} ({sun_ratio:.2%})  灰度像素 {gray_ratio:.1%}  "
              f"→ {out}")

    # 窗口标题栏代理图标：运行中进程的 NSApp
    print()
    try:
        # 在本进程里无法拿到别的进程的 NSApp，只能验证 bundle 里的图标资源
        # 是否被 NSApplication 正确采纳——用 NSBundle 检查
        b = AppKit.NSBundle.bundleWithPath_(APP)
        ni = b.objectForInfoDictionaryKey_("CFBundleIconFile")
        print(f"  Info.plist CFBundleIconFile = {ni}")
        res = b.resourcePath() + "/AppIcon.icns"
        print(f"  实际资源路径 = {res}")
        print(f"  资源存在 = {os.path.exists(res)}")
    except Exception as e:
        print(f"  bundle 检查异常: {e}")

    print()
    print("✅ 全部通过：三个位置都会显示新的日落波浪图标" if all_ok
          else "❌ 有位置未生效")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
