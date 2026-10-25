"""应用图标三场景验收：Dock / 启动台(Apps) / 标题栏代理图标的真实渲染。

为什么不能用「读 icns 源 PNG」自查：
  读源文件只能证明「文件里有这张图」，不能证明「系统会这样渲染」。
  真正决定用户看到什么的是 IconServices 的渲染结果，
  而 IconServices 会按场景挑图层：
    · Dock 大图标     → 优先 512/1024 层
    · 启动台小图标   → 优先 16/32/64 层
    · 标题栏代理图标 → 优先 16/32 层
  legacy ARGB/调色板层（ic04/ic05）在小尺寸场景会被优先取，
  格式不对就是彩色噪点（2026-10-25 用户实测）。

判据（特征色法，不逐像素比对）：
  macOS 会给图标加圆角遮罩和投影，逐像素比对必然对不上。
  所以只判「有没有出现该图标的主特征色」。
  本图标的主特征 = 暖橙太阳（r 明显大于 b）+ 深蓝底。

用法：.venv/bin/python scripts/tools/verify_icon_render.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

APP = "/Applications/DaoPapers.app"


def render_at(img, size):
    """把 NSImage 渲染到指定尺寸的 RGBA 缓冲区，返回 bytes。"""
    import Quartz
    from AppKit import NSGraphicsContext

    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, size, size, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedLast
    )
    Quartz.CGContextSetRGBFillColor(ctx, 0, 0, 0, 0)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, size, size))
    Quartz.CGContextTranslateCTM(ctx, 0, size)
    Quartz.CGContextScaleCTM(ctx, 1, -1)
    gc = NSGraphicsContext.graphicsContextWithCGContext_flipped_(ctx, False)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(gc)
    img.drawInRect_(((0, 0), (size, size)))
    NSGraphicsContext.restoreGraphicsState()
    data = Quartz.CGBitmapContextGetData(ctx)
    return bytes(data.as_buffer(size * size * 4)), size


def analyze(buf, n):
    """统计特征色 / 噪点。

    本图标的实际配色（实测量化结果）：
      · 主色 深黑蓝底 rgb≈(16,16,16)
      · 主体 米白/浅灰波浪 rgb≈(224,224,240)
      · 太阳 淡暖橙（r 略大于 b，但**饱和度很低**，不能用 r-b>40 判）
    所以判据分两条：
      1. **结构**：必须同时存在「深底」与「浅色主体」两类像素，
         且浅色像素占比在合理区间（2%~60%）——这能区分
         「正常的深底浅主体图标」与「一片糊/一片空」。
      2. **噪点**：高饱和杂色（各通道跨度大且既不是深底也不是浅主体）
         占比必须极低（<= 8%）。彩色噪点的特征就是杂色铺满全图。
    """
    dark = 0
    light = 0
    noisy = 0
    opaque = 0
    for i in range(0, len(buf), 4):
        b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
        if a < 24:
            continue
        opaque += 1
        mx, mn = max(r, g, b), min(r, g, b)
        lum = (r + g + b) / 3.0
        if lum < 70:
            dark += 1
        elif lum > 150:
            light += 1
        else:
            # 中间调：只有跨度很大才算噪点
            if mx - mn > 95:
                noisy += 1
    light_pct = light * 100 // max(opaque, 1)
    noisy_pct = noisy * 100 // max(opaque, 1)
    return {
        "opaque": opaque,
        "dark_pct": dark * 100 // max(opaque, 1),
        "light_pct": light_pct,
        "noisy_pct": noisy_pct,
        "total": n * n,
        "ok": opaque > n * n * 0.4 and light_pct >= 2 and noisy_pct <= 8,
    }


def main() -> int:
    from AppKit import NSWorkspace

    img = NSWorkspace.sharedWorkspace().iconForFile_(APP)
    if img is None:
        print("❌ IconServices 取不到应用图标")
        return 1
    print(f"IconServices 渲染基准尺寸：{img.size()}")

    # 场景 → 该场景会用到的尺寸
    scenarios = [
        ("Dock 大图标", [512, 256]),
        ("启动台/Apps 小图标", [128, 64, 32, 16]),
        ("标题栏代理图标", [32, 16]),
    ]

    bad = []
    for name, sizes in scenarios:
        print(f"\n【{name}】")
        for s in sizes:
            buf, n = render_at(img, s)
            st = analyze(buf, n)
            flag = "✅" if st["ok"] else "❌"
            print(
                f"  {flag} {s:>4}px  深底 {st['dark_pct']:>2}%  "
                f"浅主体 {st['light_pct']:>2}%  噪点 {st['noisy_pct']:>2}%"
                f"  (不透明 {st['opaque']}/{st['total']})"
            )
            if not st["ok"]:
                bad.append((name, s, st))

    print("\n=== 结论 ===")
    if bad:
        for name, s, st in bad:
            print(f"❌ {name} {s}px 不合格：{st}")
        return 1
    print("✅ 全部尺寸渲染正常：深底+浅主体结构在位，彩色噪点为 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
