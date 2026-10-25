"""菜单栏图标 22pt 下的可辨识度体检（不靠肉眼，靠像素测量）。

检查项：
  1. 底板是否完整（alpha 覆盖率、四角是否被裁）
  2. 太阳是否还看得出（暖色像素占比与亮度对比）
  3. 三层丝带是否还能分层（按亮度聚类，看层数）
  4. 描边是否可见（底板边缘一圈的亮度是否高于底板内部）
"""
from __future__ import annotations

import os
import sys

from AppKit import NSBitmapImageRep

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P = os.path.join(ROOT, "assets", "tray", "appicon@2x.png")


def load(path):
    rep = NSBitmapImageRep.imageRepWithContentsOfFile_(path)
    return rep


def luma(r, g, b):
    """colorAtX_y_ 返回的分量是 0..1，这里换算成 0..255 便于读数。"""
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) * 255.0


def main():
    rep = load(P)
    W, H = rep.pixelsWide(), rep.pixelsHigh()
    print(f"图标：{os.path.relpath(P, ROOT)}  {W}x{H}px")

    # 1. alpha 覆盖
    opaque = 0
    corner_alpha = []
    for y in range(H):
        for x in range(W):
            c = rep.colorAtX_y_(x, y)
            if c.alphaComponent() > 0.5:
                opaque += 1
            if (x, y) in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)):
                corner_alpha.append(round(c.alphaComponent(), 2))
    print(f"1) 不透明像素占比 {opaque/(W*H)*100:.1f}%   四角 alpha={corner_alpha}")

    # 2. 暖色（太阳）像素：R 明显高于 B
    warm = []
    for y in range(H):
        for x in range(W):
            c = rep.colorAtX_y_(x, y)
            if c.alphaComponent() > 0.5 and c.redComponent() - c.blueComponent() > 0.08:
                warm.append(luma(c.redComponent(), c.greenComponent(), c.blueComponent()))
    if warm:
        print(f"2) 暖色像素 {len(warm)} 个（{len(warm)/(W*H)*100:.1f}%），平均亮度 {sum(warm)/len(warm):.0f}")
    else:
        print("2) 暖色像素 0 —— 太阳在 22pt 下已经糊掉了！")

    # 3. 全图亮度直方图（看能否分出 层）
    buckets = [0] * 6
    for y in range(H):
        for x in range(W):
            c = rep.colorAtX_y_(x, y)
            if c.alphaComponent() <= 0.5:
                continue
            L = luma(c.redComponent(), c.greenComponent(), c.blueComponent())
            buckets[min(5, int(L / 51))] += 1
    total = sum(buckets) or 1
    names = ["0-51 暗", "51-102", "102-153", "153-204", "204-255", "255+"]
    print("3) 亮度分布：" + "  ".join(f"{n}:{v/total*100:.0f}%" for n, v in zip(names, buckets)))

    # 4. 描边：沿底板中线扫一圈，看最外 1-2px 像素亮度 vs 内部 4px 处
    mid = H // 2
    outer, inner = [], []
    for x in range(W):
        c_out = rep.colorAtX_y_(x, mid)
        c_in = rep.colorAtX_y_(x, mid)
        outer.append(luma(c_out.redComponent(), c_out.greenComponent(), c_out.blueComponent()))
    # 找到水平方向上第一个不透明像素与最后一个
    xs = [x for x in range(W) if rep.colorAtX_y_(x, mid).alphaComponent() > 0.5]
    if xs:
        left, right = xs[0], xs[-1]
        edge = []
        for x in range(left, min(left + 4, W)):
            c = rep.colorAtX_y_(x, mid)
            edge.append(luma(c.redComponent(), c.greenComponent(), c.blueComponent()))
        print(f"4) 水平中线：不透明区间 x=[{left},{right}]  左边缘 4px 亮度 {edge}")
        # 底板内部（离边缘 6px 处）亮度参考
        if left + 6 < right:
            c = rep.colorAtX_y_(left + 6, mid)
            print(f"   内部 6px 处亮度 {luma(c.redComponent(), c.greenComponent(), c.blueComponent()):.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
