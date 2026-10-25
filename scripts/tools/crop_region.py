#!/usr/bin/env python3
"""按原始像素精确裁剪并放大 PNG（不做任何坐标系变换，避免裁错位置）。

为什么不用 CGImageDrawImage 做裁剪：
    CGImageDrawImage 在默认 y 向上的 CTM 里会把图像上下翻转，
    配合 translate 很容易裁到错误的区域（实测连续裁到全白）。
    这里直接读原始像素、逐行 memcpy，再手工上下翻转写入，
    坐标语义 = 图片左上角原点，和人眼看到的一致。

用法：
    python scripts/tools/crop_region.py <src.png> <out.png> <x> <y> <w> <h> [scale]
    坐标单位是图片的像素点（不是屏幕点）。
"""
from __future__ import annotations

import struct
import sys

import Quartz
from Foundation import NSURL


def read_png_rgba(path):
    """返回 (width, height, bytearray RGBA)。"""
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
    if src is None:
        raise RuntimeError(f"打不开图片：{path}")
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    w = Quartz.CGImageGetWidth(cg)
    h = Quartz.CGImageGetHeight(cg)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, w, h, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedLast
    )
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, w, h), cg)
    data = Quartz.CGBitmapContextGetData(ctx)
    buf = bytearray(bytes(data.as_buffer(w * h * 4)))
    return w, h, buf


def write_png(path, w, h, buf):
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, w, h, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedLast
    )
    data = Quartz.CGBitmapContextGetData(ctx)
    n = w * h * 4
    data.as_buffer(n)[:] = bytes(buf[:n])
    out = Quartz.CGBitmapContextCreateImage(ctx)
    dest = Quartz.CGImageDestinationCreateWithURL(
        NSURL.fileURLWithPath_(path), "public.png", 1, None
    )
    Quartz.CGImageDestinationAddImage(dest, out, None)
    Quartz.CGImageDestinationFinalize(dest)


def crop_zoom(src, out, x0, y0, cw, ch, scale):
    W, H, buf = read_png_rgba(src)
    x0 = max(0, min(x0, W - 1))
    y0 = max(0, min(y0, H - 1))
    cw = min(cw, W - x0)
    ch = min(ch, H - y0)
    ow, oh = cw * scale, ch * scale
    dst = bytearray(ow * oh * 4)
    for oy in range(oh):
        sy = y0 + oy // scale
        srow = (sy * W) * 4
        drow = oy * ow * 4
        for ox in range(ow):
            sx = x0 + ox // scale
            so = srow + sx * 4
            do = drow + ox * 4
            dst[do:do + 4] = buf[so:so + 4]
    write_png(out, ow, oh, dst)
    print(f"源 {W}x{H} → 裁 ({x0},{y0}) {cw}x{ch} 放大 {scale}x → {out} ({ow}x{oh})")


def main():
    if len(sys.argv) < 6:
        print(__doc__)
        return 1
    src, out = sys.argv[1], sys.argv[2]
    x0, y0, cw, ch = (int(v) for v in sys.argv[3:7])
    scale = int(sys.argv[7]) if len(sys.argv) > 7 else 1
    crop_zoom(src, out, x0, y0, cw, ch, scale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
