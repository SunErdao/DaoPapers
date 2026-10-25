"""把菜单栏图标渲染成字符画，用于自检小尺寸下形状是否走样。

按颜色语义分类（不依赖肉眼）：
  空格 = 透明
  .    = 底板近黑
  -    = 影层深灰
  o    = 暖层橘褐
  O    = 暖层亮部
  #    = 白层奶白
  @    = 太阳（最亮暖色）
"""
from __future__ import annotations

import os
import sys

from AppKit import NSBitmapImageRep

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P = os.path.join(ROOT, "assets", "tray", "appicon@2x.png")


def classify(r, g, b, a):
    if a < 0.5:
        return " "
    L = 0.2126 * r + 0.7152 * g + 0.0722 * b
    warm = r - b
    if warm > 0.30 and L > 0.55:
        return "@"          # 太阳
    if warm > 0.12 and L > 0.42:
        return "O"          # 暖层亮部
    if warm > 0.10:
        return "o"          # 暖层暗部
    if L > 0.45:
        return "#"          # 白层
    if L > 0.12:
        return "-"          # 影层
    return "."              # 底板


def main():
    rep = NSBitmapImageRep.imageRepWithContentsOfFile_(P)
    W, H = rep.pixelsWide(), rep.pixelsHigh()
    print(f"{os.path.relpath(P, ROOT)}  {W}x{H}  （@2x，逻辑 22pt）\n")
    for y in range(H):
        row = []
        for x in range(W):
            c = rep.colorAtX_y_(x, y)
            row.append(classify(c.redComponent(), c.greenComponent(),
                                c.blueComponent(), c.alphaComponent()))
        print("".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
