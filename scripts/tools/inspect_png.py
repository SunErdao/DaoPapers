"""SVG 渲染结果体检：采样关键点色值 + 结构字符画（模型无法读图，只能程序化核对）。"""
import sys
from AppKit import NSBitmapImageRep

path = sys.argv[1]
size = int(sys.argv[2]) if len(sys.argv) > 2 else 512
rep = NSBitmapImageRep.imageRepWithContentsOfFile_(path)
W, H = rep.pixelsWide(), rep.pixelsHigh()
print(f"{path}: {W}x{H}")


def rgba(x, y):
    c = rep.colorAtX_y_(int(x), int(y))
    return (round(c.redComponent(), 3), round(c.greenComponent(), 3),
            round(c.blueComponent(), 3), round(c.alphaComponent(), 3))


print("\n--- 关键点采样（按 1024 设计坐标换算）---")
pts = [
    ("太阳中心", 649, 291),
    ("太阳右上", 700, 250),
    ("白浪中段", 450, 460),
    ("暖浪左", 250, 540),
    ("暖浪右暗端", 780, 620),
    ("深浪左", 250, 660),
    ("深浪中", 520, 700),
    ("底板左上角外", 5, 5),
    ("底板内上", 60, 60),
    ("右下空地", 980, 900),
]
for name, dx, dy in pts:
    x, y = dx * W / 1024.0, dy * H / 1024.0
    print(f"  {name:12s} ({dx:4d},{dy:4d}) -> {rgba(x, y)}")

print("\n--- 结构字符画 ---")
cols = 64
rows = 32
for r in range(rows):
    line = []
    for c in range(cols):
        x = int((c + 0.5) * W / cols)
        y = int((r + 0.5) * H / rows)
        R, G, B, A = rgba(x, y)
        if A < 0.4:
            line.append(" ")
            continue
        L = 0.2126 * R + 0.7152 * G + 0.0722 * B
        sat = max(R, G, B) - min(R, G, B)
        if sat > 0.18 and R > 0.55 and G > 0.6:
            line.append("O")   # 暖亮（太阳）
        elif sat > 0.10 and R > G:
            line.append("w")   # 暖橘（中间浪）
        elif L > 0.62:
            line.append("#")   # 奶白（前景浪）
        elif L > 0.30:
            line.append("+")
        elif L > 0.13:
            line.append("-")
        else:
            line.append(".")
    print("  " + "".join(line))
