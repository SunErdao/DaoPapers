"""从应用图标（assets/AppIcon-1024.png）的主体图形生成菜单栏托盘图标。

图形语言与 AppIcon 完全一致：太阳圆盘 + 一长一短两条横线（太阳与海平线），
按菜单栏 22pt 密度重新平衡布局（AppIcon 原坐标偏上，直接搬过来会显得飘）。

产出（每色 × 每样式 × @1x/@2x，共 12 个）：
  glyph：透明底单色剪影（跟随系统明暗的模板图）
  solid：同色 squircle 圆角底板 + 剪影挖空（衬底版）

用法：.venv/bin/python scripts/build/gen_tray_icons.py
改图形只需改下面的 GEO 参数；改完重新生成即可，托盘代码无需动。
"""

from __future__ import annotations

import os
import sys

from AppKit import (
    NSAffineTransform,
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSGraphicsContext,
    NSMakeRect,
    NSMakeSize,
    NSPNGFileType,
)
from Foundation import NSMutableDictionary

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "assets", "tray")

# 设计坐标（24×24 画布），由 AppIcon-1024.png 像素扫描归一化后按菜单栏密度重排：
#   太阳中心 (0.5, 0.53) 直径 0.25 → 菜单栏版放大到 35% 高并居中
#   长线 y 0.615 粗 0.088 跨 0.135–0.865；短线 y 0.738 粗 0.05 跨 0.400–0.740
GEO = {
    "sun": (12.0, 9.5, 4.2),           # cx, cy, r
    "long": (4.4, 13.5, 15.2, 2.2),    # x, y, w, h
    "short": (10.2, 17.55, 7.2, 1.5),  # x, y, w, h
}

PT = 22.0                      # 逻辑尺寸 22pt，与系统菜单栏图标等大
SCALES = (1, 2)                # @1x=22px，@2x=44px
COLORS = {
    "black": (0.0, 0.0, 0.0, 1.0),
    "white": (1.0, 1.0, 1.0, 1.0),
    "gray": (0.557, 0.557, 0.576, 1.0),  # iOS systemGray
}


def _new_canvas(pixels: int) -> NSBitmapImageRep:
    """精确 pixels×pixels 像素的绘图位图（不受屏幕 backing scale 影响）。"""
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, pixels, pixels, 8, 4, True, False,
        "NSCalibratedRGBColorSpace", pixels * 4, 32,
    )
    return rep


def _enter(rep: NSBitmapImageRep, pixels: int) -> None:
    """把 rep 设为当前绘图上下文，并叠上 24×24 设计坐标 → 像素的翻转变换。"""
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    t = NSAffineTransform.transform()
    t.translateXBy_yBy_(0, pixels)
    t.scaleXBy_yBy_(pixels / 24.0, -pixels / 24.0)
    t.concat()


def _shape_paths():
    scx, scy, sr = GEO["sun"]
    paths = [
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(scx - sr, scy - sr, sr * 2, sr * 2)
        )
    ]
    for key in ("long", "short"):
        x, y, w, h = GEO[key]
        paths.append(
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, w, h), h / 2, h / 2
            )
        )
    return paths


def render(style: str, color, scale: int, out_path: str) -> None:
    pixels = int(round(PT * scale))
    rep = _new_canvas(pixels)
    _enter(rep, pixels)

    try:
        paint = NSColor.colorWithCalibratedRed_green_blue_alpha_(*color)
        shapes = _shape_paths()

        if style == "solid":
            # squircle 近似：24×24 圆角矩形，r≈5.6（Apple 风格约 22.7%）
            plate = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(0.6, 0.6, 22.8, 22.8), 5.6, 5.6
            )
            paint.set()
            plate.fill()
            # 图形区擦除（挖空）→ 底板上的透明剪影
            # NSCompositeClear = 0；NSCompositeSourceOver = 2
            NSGraphicsContext.currentContext().setCompositingOperation_(0)
            for p in shapes:
                p.fill()
            NSGraphicsContext.currentContext().setCompositingOperation_(2)
        else:
            paint.set()
            for p in shapes:
                p.fill()
    finally:
        NSGraphicsContext.restoreGraphicsState()

    props = NSMutableDictionary.dictionaryWithObject_forKey_(
        False, "NSImageInterlaced"
    )
    png = rep.representationUsingType_properties_(NSPNGFileType, props)
    ok = png.writeToFile_atomically_(out_path, True)
    if not ok:
        raise RuntimeError(f"写入失败：{out_path}")


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    n = 0
    for style in ("glyph", "solid"):
        for cname, cval in COLORS.items():
            for scale in SCALES:
                suffix = "@2x.png" if scale == 2 else ".png"
                out = os.path.join(OUT_DIR, f"{style}_{cname}{suffix}")
                render(style, cval, scale, out)
                print(f"生成 {os.path.relpath(out, ROOT)}")
                n += 1
    print(f"共 {n} 个图标 → {os.path.relpath(OUT_DIR, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
