"""图像处理：用 AppKit 完成按屏幕尺寸的重新合成（零第三方依赖）。

fill    裁剪填满：等比放大到铺满，居中裁掉溢出部分
fit     完整显示：等比缩放到完整可见，四周留白（底色可配）
stretch 拉伸铺满：直接拉到屏幕尺寸（可能变形）
center  居中原始：按原始像素居中，超出部分裁掉
"""

from __future__ import annotations

import os

from AppKit import (
    NSBezierPath,
    NSBitmapImageFileTypeJPEG,
    NSBitmapImageRep,
    NSColor,
    NSCompositingOperationSourceOver,
    NSImage,
    NSImageCompressionFactor,
)
from Foundation import NSMakeRect

MODES = ("fill", "fit", "stretch", "center")


def _ns_color(hex_str: str):
    text = (hex_str or "#000000").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        r = int(text[0:2], 16) / 255.0
        g = int(text[2:4], 16) / 255.0
        b = int(text[4:6], 16) / 255.0
    except ValueError:
        r = g = b = 0.0
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)


# JPEG 的 SOF 标记（Start Of Frame，含尺寸）：Baseline / Extended / Progressive /
# 无损及算术编码变体。遇到其中任一即可读到宽高。
_JPEG_SOF_MARKERS = frozenset(
    (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)
)


def _jpeg_size(fp) -> tuple:
    """扫描 JPEG 段结构，返回 SOF 里的 (宽, 高)；找不到返回 (0, 0)。"""
    fp.seek(2)  # 跳过 SOI
    while True:
        first = fp.read(1)
        if not first or first != b"\xff":
            return (0, 0)
        marker = fp.read(1)
        while marker == b"\xff":  # 填充字节
            marker = fp.read(1)
        if not marker:
            return (0, 0)
        m = marker[0]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:  # SOI/TEM/RSTn：无长度字段
            continue
        if m == 0xD9:  # EOI
            return (0, 0)
        seg = fp.read(2)
        if len(seg) < 2:
            return (0, 0)
        length = int.from_bytes(seg, "big")
        if length < 2:
            return (0, 0)
        if m in _JPEG_SOF_MARKERS:
            sof = fp.read(5)  # 精度(1) + 高(2) + 宽(2)
            if len(sof) < 5:
                return (0, 0)
            h = int.from_bytes(sof[1:3], "big")
            w = int.from_bytes(sof[3:5], "big")
            return (w, h) if w > 0 and h > 0 else (0, 0)
        fp.seek(length - 2, 1)


def image_size(path: str):
    """返回 (宽, 高)，读取失败返回 (0, 0)。

    纯 Python 解析（JPEG 扫 SOF 段 / PNG 读 IHDR）：不实例化 NSImage。
    调用方（引擎下载回写、本地源扫描）都在后台线程，NSImage 有主线程纪律；
    且这样也免掉一次完整的 AppKit 图像解码。
    """
    try:
        with open(path, "rb") as fp:
            head = fp.read(26)
            if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                w = int.from_bytes(head[16:20], "big")
                h = int.from_bytes(head[20:24], "big")
                return (w, h) if w > 0 and h > 0 else (0, 0)
            if head[:2] == b"\xff\xd8":
                return _jpeg_size(fp)
    except OSError:
        pass
    return (0, 0)


def _dest_rect(iw: float, ih: float, w: float, h: float, mode: str):
    from Foundation import NSMakeRect as _rect

    if mode == "stretch":
        return _rect(0.0, 0.0, float(w), float(h))
    if mode == "center":
        return _rect((w - iw) / 2.0, (h - ih) / 2.0, float(iw), float(ih))
    if iw <= 0 or ih <= 0:
        return _rect(0.0, 0.0, float(w), float(h))
    scale = (w / iw) if mode == "stretch" else None
    if mode == "fill":
        scale = max(w / iw, h / ih)
    else:  # fit
        scale = min(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    return _rect((w - dw) / 2.0, (h - dh) / 2.0, dw, dh)


def compose(src_path: str, dst_path: str, width: int, height: int,
            mode: str = "fill", bg_color: str = "#000000", quality: float = 0.94) -> bool:
    """把 src_path 合成到指定像素尺寸并写出 JPEG。成功返回 True。"""
    if not os.path.exists(src_path) or width <= 0 or height <= 0:
        return False
    src = NSImage.alloc().initWithContentsOfFile_(src_path)
    if src is None:
        return False
    size = src.size()
    if size.width <= 0 or size.height <= 0:
        return False

    mode = mode if mode in MODES else "fill"
    w, h = float(width), float(height)

    canvas = NSImage.alloc().initWithSize_((w, h))
    canvas.lockFocus()
    try:
        _ns_color(bg_color).setFill()
        NSBezierPath.fillRect_(NSMakeRect(0.0, 0.0, w, h))
        rect = _dest_rect(float(size.width), float(size.height), w, h, mode)
        src.drawInRect_fromRect_operation_fraction_(
            rect, NSMakeRect(0.0, 0.0, 0.0, 0.0), NSCompositingOperationSourceOver, 1.0
        )
        rep = NSBitmapImageRep.alloc().initWithFocusedViewRect_(NSMakeRect(0.0, 0.0, w, h))
    finally:
        canvas.unlockFocus()

    if rep is None:
        return False
    data = rep.representationUsingType_properties_(
        NSBitmapImageFileTypeJPEG, {NSImageCompressionFactor: quality}
    )
    if not data:
        return False
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    # 不用 atomically（它会走临时文件+改名），直接写；写完校验文件大小
    if not data.writeToFile_atomically_(dst_path, False):
        return False
    try:
        return os.path.getsize(dst_path) > 20 * 1024
    except OSError:
        return False
