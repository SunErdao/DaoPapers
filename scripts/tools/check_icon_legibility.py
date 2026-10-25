"""应用图标多尺寸可辨识度体检。

关键指标：小尺寸（16/32px）下太阳与三层浪是否还分得开。
太阳用「暖色高饱和」指纹定位，浪层用亮度分带判定。
"""
import os
import sys

from AppKit import NSBitmapImageRep

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICONSET = os.path.join(ROOT, "assets", "AppIcon.iconset")


def analyze(path):
    rep = NSBitmapImageRep.imageRepWithContentsOfFile_(path)
    W, H = rep.pixelsWide(), rep.pixelsHigh()
    if W == 0:
        return None
    sun = 0
    opaque = 0
    bands = {}
    for y in range(H):
        for x in range(W):
            c = rep.colorAtX_y_(x, y)
            if c.alphaComponent() < 0.5:
                continue
            opaque += 1
            R, G, B = c.redComponent(), c.greenComponent(), c.blueComponent()
            L = 0.2126 * R + 0.7152 * G + 0.0722 * B
            sat = max(R, G, B) - min(R, G, B)
            # 太阳指纹：暖且亮（R-B 差值大且亮度高）
            if R - B > 0.18 and L > 0.55:
                sun += 1
            key = "白浪" if L > 0.60 else ("暖浪" if (sat > 0.08 and R > G) else "暗部")
            bands[key] = bands.get(key, 0) + 1
    return {
        "px": W, "opaque": opaque, "sun": sun,
        "sun_pct": sun / max(opaque, 1) * 100,
        "bands": bands,
    }


files = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_256x256.png", 256),
    ("icon_512x512.png", 512),
]
print(f"{'文件':22s} {'尺寸':>8s} {'不透明%':>8s} {'太阳%':>7s}  分层")
for name, expect in files:
    p = os.path.join(ICONSET, name)
    if not os.path.exists(p):
        print(f"{name:22s}  缺失")
        continue
    r = analyze(p)
    if r is None:
        print(f"{name:22s}  读取失败")
        continue
    b = r["bands"]
    print(f"{name:22s} {r['px']:>4d}px {r['opaque']/(r['px']**2)*100:7.1f}% "
          f"{r['sun_pct']:6.1f}%  白浪{b.get('白浪',0):5d} 暖浪{b.get('暖浪',0):5d} "
          f"暗部{b.get('暗部',0):5d}")

print("\n--- 16px 字符画（放大 2 倍看细节）---")
p = os.path.join(ICONSET, "icon_16x16@2x.png")
rep = NSBitmapImageRep.imageRepWithContentsOfFile_(p)
for y in range(0, rep.pixelsHigh(), 2):
    row = ""
    for x in range(rep.pixelsWide()):
        c = rep.colorAtX_y_(x, y)
        if c.alphaComponent() < 0.5:
            row += " "
            continue
        R, G, B = c.redComponent(), c.greenComponent(), c.blueComponent()
        L = 0.2126 * R + 0.7152 * G + 0.0722 * B
        sat = max(R, G, B) - min(R, G, B)
        if R - B > 0.18 and L > 0.55:
            row += "O"
        elif sat > 0.08 and R > G:
            row += "w"
        elif L > 0.60:
            row += "#"
        elif L > 0.28:
            row += "+"
        elif L > 0.12:
            row += "-"
        else:
            row += "."
    print("  " + row)
