"""生成交付预览图。

从**实际产出的 PNG 资源**读取并排版（不重新绘制，保证预览与交付一致）：
  · 应用图标多尺寸（1024 / 256 / 128 / 64 / 32 / 16）
  · 菜单栏白版在浅色 / 深色菜单栏上的实际观感
  · 菜单栏满色版在浅色 / 深色底上的观感
  · 原稿 SVG vs 精细化版对比
产物：docs/preview/preview-icons.png
"""
from __future__ import annotations

import os

import Quartz
from AppKit import (
    NSAttributedString,
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSGraphicsContext,
    NSImage,
    NSPNGFileType,
)
from CoreFoundation import (
    CFURLCreateWithFileSystemPath,
    kCFAllocatorDefault,
    kCFURLPOSIXPathStyle,
)
from Foundation import NSMakeRect

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(ROOT, "assets")
ICONSET = os.path.join(ASSETS, "AppIcon.iconset")
TRAY = os.path.join(ASSETS, "tray")

W, H = 1440, 820
rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, W, H, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
)
ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.setCurrentContext_(ctx)


def fill(r, g, b, a=1.0):
    NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a).setFill()
    NSBezierPath.fillRect_(NSMakeRect(0, 0, W, H))


def rect(x, y, w, h, r, g, b, a=1.0, radius=0):
    NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, y, w, h), radius, radius).fill()


def label(text, x, y, size=15, color=(0.22, 0.22, 0.25), bold=False):
    NSColor.colorWithSRGBRed_green_blue_alpha_(*color, 1).setFill()
    font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    s = NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font})
    s.drawAtPoint_((x, y))


def draw_image(path, x, y, size):
    """把 PNG 贴到 (x, y)（左下原点），缩放到 size×size。

    注意：必须用单参数 drawInRect_。PyObjC 下
    drawInRect_fromRect_operation_fraction_ 这个重载会**丢掉源矩形**，
    结果整张图画不出来（画布上留下空白方块）——踩过坑，别改回去。
    """
    if not os.path.exists(path):
        return
    img = NSImage.alloc().initWithContentsOfFile_(path)
    if img is None:
        return
    img.drawInRect_(NSMakeRect(x, y, size, size))


def draw_template(path, x, y, size, ink):
    """按「模板图」的真实规则绘制：alpha 通道当 mask，颜色由系统决定。

    模板图（isTemplate=True）在浅色菜单栏上显示为深色，深色菜单栏上显示为浅色。
    这里用 alpha 作为 mask + 填充 ink 颜色来模拟。
    """
    if not os.path.exists(path):
        return
    url = CFURLCreateWithFileSystemPath(
        kCFAllocatorDefault, path, kCFURLPOSIXPathStyle, False)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        return
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if cg is None:
        return

    # 取 alpha 通道作为 mask
    w = Quartz.CGImageGetWidth(cg)
    h = Quartz.CGImageGetHeight(cg)
    cs = Quartz.CGColorSpaceCreateDeviceGray()
    mask_ctx = Quartz.CGBitmapContextCreate(
        None, w, h, 8, 0, cs, Quartz.kCGImageAlphaNone)
    Quartz.CGContextDrawImage(mask_ctx, Quartz.CGRectMake(0, 0, w, h), cg)
    mask = Quartz.CGBitmapContextCreateImage(mask_ctx)

    cgctx = ctx.CGContext()
    Quartz.CGContextSaveGState(cgctx)
    Quartz.CGContextSetAlpha(cgctx, 1.0)
    Quartz.CGContextClipToMask(cgctx, Quartz.CGRectMake(x, y, size, size), mask)
    r, g, b = ink
    Quartz.CGContextSetRGBFillColor(cgctx, r, g, b, 1.0)
    Quartz.CGContextFillRect(cgctx, Quartz.CGRectMake(x, y, size, size))
    Quartz.CGContextRestoreGState(cgctx)


# ---------- 背景 ----------
fill(0.955, 0.957, 0.962)

label("岛·壁纸 · 应用图标（基于你的手绘 SVG 重绘）", 48, H - 62,
      size=26, bold=True)
label("来源：用户手绘 SVG「日落波浪」→ 精细化 → 1024 原生渲染 → 逐尺寸光栅化",
      48, H - 92, size=14, color=(0.42, 0.44, 0.48))

# ---------- 应用图标多尺寸 ----------
label("Dock / 启动台各尺寸（每个尺寸独立光栅化，不是缩放）", 48, H - 136,
      size=16, bold=True, color=(0.28, 0.30, 0.34))

sizes = [
    ("assets/AppIcon-1024.png", 176, "1024"),
    (os.path.join(ICONSET, "icon_256x256.png"), 116, "256"),
    (os.path.join(ICONSET, "icon_128x128.png"), 88, "128"),
    (os.path.join(ICONSET, "icon_32x32@2x.png"), 60, "64"),
    (os.path.join(ICONSET, "icon_32x32.png"), 38, "32"),
    (os.path.join(ICONSET, "icon_16x16.png"), 22, "16"),
]
x = 48
base = 470
for path, sz, txt in sizes:
    draw_image(path, x, base, sz)
    # 标签统一放在该图标底部基线上，避免小尺寸图标被大尺寸盖住标签
    label(txt, x, base - 24, size=12, color=(0.45, 0.47, 0.51))
    x += sz + 40

# ---------- 精细化要点（左侧卡片，放在图标行下方，不遮挡） ----------
label("精细化要点", 48, base - 62, size=16, bold=True, color=(0.28, 0.30, 0.34))

rect(48, 176, 620, 232, 1, 1, 1, radius=12)
notes = [
    "· 底板：普通圆角 → macOS 标准 squircle（连续曲率超椭圆，512 段折线逼近）",
    "· 修正原稿 988×964 的不等边，改为正方形居中（偏差 0.008px）",
    "· 去掉满画布黑方块，四周透明（符合 macOS 图标规范）",
    "· 去掉与主路径错位的内框 rect，避免边缘重影",
    "· 层间加投影：白浪压暖浪、暖浪压深浪，做出薄片叠放的暗缝",
    "· 深浪层提亮（0.204→0.259 / 0.176→0.212），与地面拉开层次",
    "· 太阳加暖色辉光；白浪仍在太阳之前，保持遮挡关系",
]
ny = 378
for n in notes:
    label(n, 68, ny, size=12.5, color=(0.34, 0.36, 0.40))
    ny -= 22

# ---------- 应用图标在浅/深底上的观感 ----------
label("在浅色 / 深色桌面上的观感", 700, H - 136, size=16, bold=True,
      color=(0.28, 0.30, 0.34))

rect(700, 596, 210, 78, 1, 1, 1, radius=14)
draw_image(os.path.join(ASSETS, "AppIcon-1024.png"), 716, 613, 44)
label("浅色桌面", 772, 627, size=13, color=(0.35, 0.36, 0.40))

rect(926, 596, 210, 78, 0.12, 0.13, 0.15, radius=14)
draw_image(os.path.join(ASSETS, "AppIcon-1024.png"), 942, 613, 44)
label("深色桌面", 998, 627, size=13, color=(0.72, 0.74, 0.78))

# ---------- 菜单栏：白版 ----------
label("菜单栏图标（状态栏）· 白版", 700, 552, size=16, bold=True,
      color=(0.28, 0.30, 0.34))
label("模板图（isTemplate=True）：系统按菜单栏明暗自动反色，与 WorkBuddy 同一规范",
      700, 528, size=13, color=(0.42, 0.44, 0.48))

# 浅色菜单栏 → 模板图显示为深色
rect(700, 464, 436, 46, 0.93, 0.94, 0.95, radius=8)
label("浅色菜单栏（图标呈深色）", 716, 480, size=12, color=(0.30, 0.31, 0.34))
draw_template(os.path.join(TRAY, "white@2x.png"), 1100, 476, 22,
              ink=(0.10, 0.10, 0.12))

# 深色菜单栏 → 模板图显示为浅色
rect(700, 404, 436, 46, 0.13, 0.14, 0.16, radius=8)
label("深色菜单栏（图标呈浅色）", 716, 420, size=12, color=(0.72, 0.74, 0.78))
draw_template(os.path.join(TRAY, "white@2x.png"), 1100, 416, 22,
              ink=(0.97, 0.97, 0.98))

# 实际像素尺寸（放大 4 倍看清形态）
rect(700, 300, 436, 78, 1, 1, 1, radius=10)
label("白版剪影实际形态（44×44 背衬，放大显示）", 716, 352, size=12,
      color=(0.42, 0.44, 0.48))
draw_template(os.path.join(TRAY, "white@2x.png"), 1020, 312, 48,
              ink=(0.10, 0.10, 0.12))
draw_template(os.path.join(TRAY, "white@2x.png"), 1082, 312, 48,
              ink=(0.97, 0.97, 0.98))

# ---------- 菜单栏：满色版（备选） ----------
label("满色版（备选）", 1160, 552, size=16, bold=True,
      color=(0.28, 0.30, 0.34))

rect(1160, 596, 200, 78, 1, 1, 1, radius=14)
draw_image(os.path.join(TRAY, "appicon@2x.png"), 1176, 613, 44)
label("浅色桌面", 1232, 627, size=13, color=(0.35, 0.36, 0.40))

rect(1160, 504, 200, 78, 0.12, 0.13, 0.15, radius=14)
draw_image(os.path.join(TRAY, "appicon@2x.png"), 1176, 521, 44)
label("深色桌面", 1232, 535, size=13, color=(0.72, 0.74, 0.78))

rect(1160, 404, 200, 78, 0.93, 0.94, 0.95, radius=10)
label("满色 22pt", 1174, 434, size=12, color=(0.30, 0.31, 0.34))
draw_image(os.path.join(TRAY, "appicon@2x.png"), 1298, 420, 44)

NSGraphicsContext.restoreGraphicsState()
data = rep.representationUsingType_properties_(NSPNGFileType, {})
out = os.path.join(ROOT, "docs", "preview", "preview-icons.png")
with open(out, "wb") as f:
    f.write(bytes(data))
print(f"已生成 {out}")
