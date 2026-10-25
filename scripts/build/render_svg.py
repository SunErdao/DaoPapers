"""SVG 光栅化器：用 WKWebView 快照把 SVG 渲染成 PNG（精确像素尺寸）。

WebKit 是 macOS 自带的 SVG 渲染引擎，与 Safari 预览一致，
比用 CoreGraphics 手工复刻更忠实于设计稿。

用法：
  python scripts/build/render_svg.py <in.svg> <out.png> <size> [底色hex]
底色可选：给 hex 则合成到该底色上（用于检查透明区）
"""
import sys, os, time
import objc
from Foundation import NSURL, NSRunLoop, NSDate, NSObject, NSMakeRect, NSMakeSize
from AppKit import (NSApplication, NSBitmapImageRep, NSPNGFileType,
                    NSColor, NSBezierPath, NSGraphicsContext)
import WebKit

objc.setSignatureAllowed = True


def _snapshot_cb(state):
    """构造快照回调闭包（模块级函数，避免 PyObjC 方法原型校验）。"""
    def cb(img, err):
        state["err"] = err
        state["img"] = img
    return cb


class Renderer(NSObject):
    """WKWebView 加载 SVG 并快照。"""

    def init(self):
        self = objc.super(Renderer, self).init()
        self.state = {}
        self.state["done"] = False
        self.state["out"] = None
        self.state["size"] = 512
        self.state["bg"] = None
        return self

    # --- WKNavigationDelegate ---
    def webView_didFinishNavigation_(self, wv, nav):
        time.sleep(0.3)
        scfg = WebKit.WKSnapshotConfiguration.alloc().init()
        scfg.setRect_(wv.bounds())
        scfg.setSnapshotWidth_(float(self.state["size"]))
        wv.takeSnapshotWithConfiguration_completionHandler_(
            scfg, _snapshot_cb(self.state))
        deadline = time.time() + 20
        while not self.state["done"] and time.time() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.05))


def _write(rep, out_path, bg):
    """把快照位图写盘（可合成到底色）。"""
    if bg is not None:
        w, h = rep.pixelsWide(), rep.pixelsHigh()
        out = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, w, h, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0)
        ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(out)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.setCurrentContext_(ctx)
        bg.setFill()
        NSBezierPath.fillRect_(NSMakeRect(0, 0, w, h))
        rep.drawInRect_(NSMakeRect(0, 0, w, h))
        NSGraphicsContext.restoreGraphicsState()
        rep = out
    data = rep.representationUsingType_properties_(NSPNGFileType, {})
    with open(out_path, "wb") as f:
        f.write(bytes(data))
    return f"{rep.pixelsWide()}x{rep.pixelsHigh()}"


def render(svg_path, out_path, size, bg_hex=None):
    NSApplication.sharedApplication()
    r = Renderer.alloc().init()
    r.state["out"] = out_path
    r.state["size"] = int(size)
    bg = None
    if bg_hex:
        h = bg_hex.lstrip("#")
        bg = NSColor.colorWithSRGBRed_green_blue_alpha_(
            int(h[0:2], 16) / 255, int(h[2:4], 16) / 255,
            int(h[4:6], 16) / 255, 1.0)
        r.state["bg"] = bg

    cfg = WebKit.WKWebViewConfiguration.alloc().init()
    wv = WebKit.WKWebView.alloc().initWithFrame_configuration_(
        NSMakeRect(0, 0, size, size), cfg)
    # 关键：关闭 WebView 的默认白底，否则快照会把透明区铺成不透明白色
    try:
        wv.setValue_forKey_(False, "drawsBackground")
    except Exception:  # noqa: BLE001
        pass
    wv.setNavigationDelegate_(r)
    r.wv = wv
    # 用 HTML 包裹 SVG：可精确控制画布尺寸、背景与留白，
    # 避免 WebKit 直接打开 SVG 时按文档流铺满导致尺寸不可控。
    svg_src = open(svg_path, encoding="utf-8").read()
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;background:transparent;"
        "width:%dpx;height:%dpx;overflow:hidden}"
        "svg{display:block;width:%dpx;height:%dpx}</style></head>"
        "<body>%s</body></html>"
    ) % (size, size, size, size, svg_src)
    base = NSURL.fileURLWithPath_(os.path.dirname(os.path.abspath(svg_path)) or ".")
    wv.loadHTMLString_baseURL_(html, base)

    deadline = time.time() + 30
    while not r.state.get("img") and r.state.get("err") is None \
            and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.05))

    err = r.state.get("err")
    if err is not None:
        raise RuntimeError(f"快照错误: {err}")
    img = r.state.get("img")
    if img is None:
        raise RuntimeError("快照超时，未返回图像")
    # NSImage → 位图表示（取最大的那个，通常是 2x 快照）
    reps = img.representations()
    if not reps:
        raise RuntimeError("快照图像无 representation")
    rep = max(reps, key=lambda r: r.pixelsWide() * r.pixelsHigh())
    got = rep.pixelsWide()
    if got != int(size):
        # Retina 上快照是 2x，按比例缩放回目标尺寸（高质量重采样）
        if got % int(size) == 0:
            # Retina 上快照是 2x，按比例缩放回目标尺寸（CoreGraphics 高质量重采样）
            from Quartz import (CGBitmapContextCreate, CGImageCreateWithImageInRect,
                                CGRectMake, CGColorSpaceCreateDeviceRGB,
                                CGContextDrawImage, CGBitmapContextCreateImage,
                                CGContextSetInterpolationQuality,
                                kCGImageAlphaPremultipliedLast,
                                kCGInterpolationHigh)
            cs = CGColorSpaceCreateDeviceRGB()
            cg_src = rep.CGImage() if hasattr(rep, "CGImage") else rep.image()
            ctx = CGBitmapContextCreate(
                None, size, size, 8, 0, cs, kCGImageAlphaPremultipliedLast)
            CGContextSetInterpolationQuality(ctx, kCGInterpolationHigh)
            CGContextDrawImage(ctx, CGRectMake(0, 0, size, size),
                               CGImageCreateWithImageInRect(
                                   cg_src,
                                   CGRectMake(0, 0, rep.pixelsWide(), rep.pixelsHigh())))
            out = NSBitmapImageRep.alloc().initWithCGImage_(
                CGBitmapContextCreateImage(ctx))
            rep = out
        else:
            raise RuntimeError(
                f"快照尺寸 {got}px 与目标 {size}px 不成整数倍，无法缩放")
    return _write(rep, out_path, bg)


if __name__ == "__main__":
    svg, out, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
    bg = sys.argv[4] if len(sys.argv) > 4 else None
    print("渲染:", render(svg, out, size, bg), "->", out)
