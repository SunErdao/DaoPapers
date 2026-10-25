#!/usr/bin/env python3
"""在启动台截图里定位「彩色噪点」图标并裁出来 —— 自动、不靠肉眼找坐标。

用法：
    python scripts/tools/find_bad_icon.py <frame.png> [输出目录]

做法：
    1. 全图按 64×64 瓦片、16 像素步长扫描；
    2. 每个瓦片算「随机彩色噪点率」（判据见 verify_launchpad_icon.py）；
    3. 取噪点率最高的一片，向上合并成 128×128 的图标尺寸再裁图；
    4. 同时输出该瓦片中心坐标，方便人工核对。

为什么不用肉眼坐标：启动台重排后图标位置会变，手算缩放比例极易错位
（实测连续算错三次）。数值定位不依赖任何坐标系假设。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crop_region import read_png_rgba, crop_zoom  # noqa: E402


def noise_rate(buf, W, x, y, tile):
    """瓦片内的随机彩色噪点占比（梯度方向不一致 + 高饱和 + 大色差）。"""
    hit = 0
    total = 0
    for yy in range(y + 1, y + tile - 1):
        for xx in range(x + 1, x + tile - 1):
            i = (yy * W + xx) * 4
            il = (yy * W + xx - 1) * 4
            iu = ((yy - 1) * W + xx) * 4
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            dh = (r - buf[il]) + (g - buf[il + 1]) + (b - buf[il + 2])
            dv = (r - buf[iu]) + (g - buf[iu + 1]) + (b - buf[iu + 2])
            mx, mn = max(r, g, b), min(r, g, b)
            total += 1
            if abs(dh) + abs(dv) > 140 and mx - mn > 70:
                if (dh > 0) != (dv > 0) or dh == 0 or dv == 0:
                    hit += 1
    return hit / max(total, 1)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    frame = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "build/verify/badicon"
    os.makedirs(outdir, exist_ok=True)

    W, H, buf = read_png_rgba(frame)
    print("帧：%s（%dx%d）" % (frame, W, H))

    best = (0.0, 0, 0)
    for y in range(0, H - 64, 16):
        for x in range(0, W - 64, 16):
            r = noise_rate(buf, W, x, y, 64)
            if r > best[0]:
                best = (r, x, y)

    rate, bx, by = best
    print("噪点最重瓦片：(%d,%d) 占比 %.1f%%" % (bx, by, rate * 100))
    if rate < 0.05:
        print("→ 低于 5%% 阈值，判定：**没有坏图标**")
        print("已输出整帧缩览 → %s/whole.png" % outdir)
        crop_zoom(frame, os.path.join(outdir, "whole.png"), 0, 0, W, H, 1)
        return 0

    # 以瓦片为中心裁 160×160（一个图标的典型尺寸）
    half = 80
    x0 = max(0, min(W - 160, bx + 32 - half))
    y0 = max(0, min(H - 160, by + 32 - half))
    out = os.path.join(outdir, "bad_icon.png")
    crop_zoom(frame, out, x0, y0, 160, 160, 3)
    print("已裁出 → %s（源区域 %d,%d 160x160，3 倍放大）" % (out, x0, y0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
