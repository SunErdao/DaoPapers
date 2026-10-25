#!/usr/bin/env python3
"""在 App 进程内 dump 上报给系统的「应用图标」，看系统实际收到的是什么。

这是 DaoPapers 图标乱码调查的**决定性实验**。

背景（2026-10-25 调查结论）：
  · icns 文件本身完全健康：8 层都是合法 PNG，zlib 流长度精确匹配；
  · IconServices（NSWorkspace.iconForFile_）给 DaoPapers 与 IconProbeC
    返回**完全一致**的 32 个图层，两者噪点都是 1.0%；
  · 启动台上 IconProbeC / IconTestA（同一份 icns 字节）显示正常，
    只有**正在运行**的 DaoPapers 显示为彩色噪点；
  · 用户截图里窗口标题栏左上角的**代理图标**也是噪点 —— 那是
    setApplicationIconImage_ 上报的那张 NSImage。

因此怀疑：setApplicationIconImage_ 上报的 NSImage 在被系统
「转存成位图」时出了问题。本脚本在 App 进程内把那份 NSImage
以各种方式落盘，供离线比对。

用法（由 runner.py 调用，或手动）：
    python scripts/tools/dump_runtime_icon.py <输出目录>
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    outdir = sys.argv[1] if len(sys.argv) > 1 else "build/verify/runtime_icon"
    os.makedirs(outdir, exist_ok=True)

    import Quartz
    from AppKit import (NSApplication, NSBitmapImageRep, NSGraphicsContext,
                        NSImage, NSMakeRect)
    from Foundation import NSURL

    def save_cg(img, path):
        d = Quartz.CGImageDestinationCreateWithURL(
            NSURL.fileURLWithPath_(path), "public.png", 1, None)
        Quartz.CGImageDestinationAddImage(d, img, None)
        Quartz.CGImageDestinationFinalize(d)
        print("  →", path)

    def render(nsimage, size, path):
        cs = Quartz.CGColorSpaceCreateDeviceRGB()
        ctx = Quartz.CGBitmapContextCreate(
            None, size, size, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedLast)
        Quartz.CGContextSetRGBFillColor(ctx, 0, 0, 0, 0)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, size, size))
        gc = NSGraphicsContext.graphicsContextWithCGContext_flipped_(ctx, False)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.setCurrentContext_(gc)
        nsimage.drawInRect_(NSMakeRect(0, 0, size, size))
        NSGraphicsContext.restoreGraphicsState()
        save_cg(Quartz.CGBitmapContextCreateImage(ctx), path)

    # 1) AppKit 视图里 NSApplication 的图标图像
    app = NSApplication.sharedApplication()
    app_icon = app.applicationIconImage()
    print("NSApp.applicationIconImage() =", app_icon)
    if app_icon is None:
        print("  ！应用图标图像为 None")
        return 1

    print("  size =", app_icon.size())
    reps = app_icon.representations()
    print("  representations =", len(reps))
    for r in reps:
        try:
            print("    %-24s px %4dx%-4d  pt %gx%g" % (
                r.__class__.__name__, r.pixelsWide(), r.pixelsHigh(),
                r.size().width, r.size().height))
        except Exception as exc:
            print("    <err>", exc)

    for s in (16, 32, 64, 128, 256):
        render(app_icon, s, os.path.join(outdir, "appicon_%d.png" % s))

    # 2) 每个 representation 单独落盘（看某一层本身是否损坏）
    for i, r in enumerate(reps):
        try:
            px = r.pixelsWide()
            path = os.path.join(outdir, "rep_%02d_%dpx.png" % (i, px))
            if px <= 512:
                cs = Quartz.CGColorSpaceCreateDeviceRGB()
                ctx = Quartz.CGBitmapContextCreate(
                    None, px, px, 8, 0, cs,
                    Quartz.kCGImageAlphaPremultipliedLast)
                Quartz.CGContextSetRGBFillColor(ctx, 0, 0, 0, 0)
                Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, px, px))
                gc = NSGraphicsContext.graphicsContextWithCGContext_flipped_(
                    ctx, False)
                NSGraphicsContext.saveGraphicsState()
                NSGraphicsContext.setCurrentContext_(gc)
                r.drawInRect_(NSMakeRect(0, 0, px, px))
                NSGraphicsContext.restoreGraphicsState()
                save_cg(Quartz.CGBitmapContextCreateImage(ctx), path)
        except Exception as exc:
            print("  rep %d 渲染失败: %s" % (i, exc))

    print("\n完成，输出目录：", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
