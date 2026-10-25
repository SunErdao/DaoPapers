"""测量「层间暗缝」是否存在——立体感的关键指标。

原理：白浪下缘与暖浪上缘之间应有一条**比两侧都暗**的窄缝（投影）。
若缝的亮度不低于两侧，说明层是"贴"在一起的，没有立体感。
"""
import sys
from AppKit import NSBitmapImageRep

path = sys.argv[1]
rep = NSBitmapImageRep.imageRepWithContentsOfFile_(path)
W, H = rep.pixelsWide(), rep.pixelsHigh()


def lum(x, y):
    c = rep.colorAtX_y_(x, y)
    return 0.2126 * c.redComponent() + 0.7152 * c.greenComponent() \
        + 0.0722 * c.blueComponent()


def alpha(x, y):
    return rep.colorAtX_y_(x, y).alphaComponent()


print(f"{path}  {W}x{H}\n")
print("竖直扫描：寻找「局部极暗」的缝（亮度低于上下两侧）")
print("格式：x坐标 | 缝位置y | 缝亮度 | 上侧亮度 | 下侧亮度 | 判定\n")

# 取若干 x 位置扫描
for frac in (0.25, 0.35, 0.45, 0.55, 0.65, 0.75):
    x = int(frac * W)
    col = []
    for y in range(H):
        if alpha(x, y) < 0.5:
            col.append(None)
        else:
            col.append(lum(x, y))

    # 找局部极小点（缝）
    found = []
    for y in range(3, H - 3):
        v = col[y]
        if v is None:
            continue
        up = [col[i] for i in range(y - 3, y) if col[i] is not None]
        dn = [col[i] for i in range(y + 1, y + 4) if col[i] is not None]
        if not up or not dn:
            continue
        umin, dmin = min(up), min(dn)
        # 缝：比两侧的最小值都暗，且暗出一定量
        if v < umin - 0.012 and v < dmin - 0.012:
            found.append((y, v, umin, dmin))

    # 合并相邻缝
    merged = []
    for item in found:
        if merged and item[0] - merged[-1][0] <= 4:
            if item[1] < merged[-1][1]:
                merged[-1] = item
        else:
            merged.append(item)

    for (y, v, umin, dmin) in merged:
        depth = min(umin, dmin) - v
        ok = "有缝 ✓" if depth > 0.02 else "无明显缝 ✗"
        print(f"  x={frac:.2f} ({x:4d}) | y={y:4d} | {v:.3f} | {umin:.3f} | "
              f"{dmin:.3f} | {ok} (深度 {depth:.3f})")
    if not merged:
        print(f"  x={frac:.2f} ({x:4d}) | 未找到暗缝 ✗")
    print()
