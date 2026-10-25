"""对比两版渲染图：原稿 vs 精细化。

输出：整体 IoU、逐区域差异定位、以及并排字符画。
"""
import sys
from AppKit import NSBitmapImageRep

pa, pb = sys.argv[1], sys.argv[2]
a = NSBitmapImageRep.imageRepWithContentsOfFile_(pa)
b = NSBitmapImageRep.imageRepWithContentsOfFile_(pb)
W = min(a.pixelsWide(), b.pixelsWide())
H = min(a.pixelsHigh(), b.pixelsHigh())
print(f"A={pa} {a.pixelsWide()}x{a.pixelsHigh()}")
print(f"B={pb} {b.pixelsWide()}x{b.pixelsHigh()}")
print(f"对比区 {W}x{H}\n")


def lum(rep, x, y):
    c = rep.colorAtX_y_(x, y)
    return 0.2126 * c.redComponent() + 0.7152 * c.greenComponent() \
        + 0.0722 * c.blueComponent()


def alpha(rep, x, y):
    return rep.colorAtX_y_(x, y).alphaComponent()


# --- 1. 轮廓 IoU（前景 = 亮度 > 48 或 alpha<0.5 视为底板外） ---
for thr in (48, 120):
    both = only_a = only_b = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            ina = alpha(a, x, y) > 0.5 and lum(a, x, y) > thr
            inb = alpha(b, x, y) > 0.5 and lum(b, x, y) > thr
            if ina and inb:
                both += 1
            elif ina:
                only_a += 1
            elif inb:
                only_b += 1
    tot = both + only_a + only_b
    print(f"阈值 {thr}: 重合 {both}  仅A {only_a}  仅B {only_b}  "
          f"IoU={both/tot if tot else 0:.4f}")

# --- 2. 关键点色值对比 ---
print("\n--- 关键点色值 A(原稿) → B(精细化) ---")
pts = [
    ("太阳中心", 649, 291),
    ("太阳上缘", 649, 190),
    ("太阳下缘", 649, 390),
    ("白浪左", 300, 440),
    ("白浪中", 500, 420),
    ("白浪右", 780, 470),
    ("暖浪左", 260, 540),
    ("暖浪右", 760, 600),
    ("深浪左", 250, 660),
    ("深浪中", 520, 720),
    ("深浪右", 800, 600),
    ("地面空地", 120, 150),
    ("底板左外", 4, 512),
]
for name, dx, dy in pts:
    x, y = int(dx * W / 1024), int(dy * H / 1024)
    ca = a.colorAtX_y_(x, y)
    cb = b.colorAtX_y_(x, y)
    sa = (round(ca.redComponent(), 3), round(ca.greenComponent(), 3),
          round(ca.blueComponent(), 3), round(ca.alphaComponent(), 2))
    sb = (round(cb.redComponent(), 3), round(cb.greenComponent(), 3),
          round(cb.blueComponent(), 3), round(cb.alphaComponent(), 2))
    print(f"  {name:10s} A={sa}  B={sb}")

# --- 3. 层间对比度（关键：层与层是否分得开） ---
print("\n--- 层次可分性（垂直扫过 x=500 的亮度剖面） ---")
prof_a = []
prof_b = []
for dy in range(300, 820, 20):
    y = int(dy * H / 1024)
    prof_a.append(round(lum(a, int(500 * W / 1024), y), 3))
    prof_b.append(round(lum(b, int(500 * W / 1024), y), 3))
print("  dy :", " ".join(f"{d:4d}" for d in range(300, 820, 20)))
print("  A  :", " ".join(f"{v:4.2f}" for v in prof_a))
print("  B  :", " ".join(f"{v:4.2f}" for v in prof_b))

# --- 4. 并排字符画 ---
print("\n--- 字符画 A(原稿) | B(精细化) ---")
cols, rows = 58, 29
for r in range(rows):
    la, lb = [], []
    for c in range(cols):
        x = int((c + 0.5) * W / cols)
        y = int((r + 0.5) * H / rows)
        for rep, acc in ((a, la), (b, lb)):
            cc = rep.colorAtX_y_(x, y)
            R, G, B = cc.redComponent(), cc.greenComponent(), cc.blueComponent()
            if cc.alphaComponent() < 0.4:
                acc.append(" ")
                continue
            L = 0.2126 * R + 0.7152 * G + 0.0722 * B
            sat = max(R, G, B) - min(R, G, B)
            if sat > 0.16 and R > 0.55 and G > 0.55:
                acc.append("O")
            elif sat > 0.09 and R > G:
                acc.append("w")
            elif L > 0.60:
                acc.append("#")
            elif L > 0.32:
                acc.append("+")
            elif L > 0.17:
                acc.append("-")
            elif L > 0.07:
                acc.append(".")
            else:
                acc.append(" ")
    print("  " + "".join(la) + " | " + "".join(lb))
