#!/usr/bin/env python3
"""启动台（macOS 26 的「应用程序」/ Apps.app）图标渲染自动验收。

为什么需要这个脚本（2026-10-25）：
    1. `screencapture` 抓整屏**随机撕裂**——有时抓到干净帧，有时抓到
       WindowServer 重绘的中间帧（表现为整屏斜向条纹）。肉眼判断因此不可靠。
    2. 启动台是 Dock 进程画的，一旦被别的窗口抢焦点就自动关闭，
       所以「截到了启动台」本身就需要自动判定，不能靠假设。
    3. 「图标是不是彩色噪点」必须用**数值判据**，不能用「看起来像不像」。

本脚本做四件事：
    A. 连拍 N 帧（间隔可配），每帧用「tab 栏浅色块占比」判定启动台是否在画面；
    B. 自动挑出启动台真正可见的那一帧；
    C. 在该帧上跑**严格噪点检测**（相邻像素差 + 高饱和才算噪点，
       可排除 WorkBuddy 界面自身的彩色元素）；
    D. 输出数值结论 + 裁出图标区图片供人眼复核。

判据说明（噪点）：
    真正的坏图（icns 渲染错误）特征是**逐像素随机彩色**——相邻像素差极大
    且饱和度高。正常图标是平滑渐变，相邻像素差小；WorkBuddy 的品牌绿虽然
    高饱和，但相邻像素差小（平滑色块），会被这个判据排除。

用法：
    python scripts/tools/verify_launchpad_icon.py [输出目录]
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import time

import Quartz
from Foundation import NSURL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crop_region import read_png_rgba, crop_zoom  # noqa: E402

# 启动台窗口大致覆盖屏幕中部；下面这些坐标是 5K(5120x2880) 全屏像素下的经验值。
LAUNCHPAD_BOX = (400, 860, 1700, 1000)   # x, y, w, h（tab 栏 + 第一行图标）
ICON_ROW = (400, 900, 1700, 900)         # 图标网格区


def grab(path: str) -> bool:
    r = subprocess.run(["screencapture", "-x", path], capture_output=True)
    return r.returncode == 0 and os.path.exists(path)


def tab_bar_white_ratio(buf, W, x, y, w, h) -> float:
    """启动台顶部有一排浅色圆角 tab 按钮；白像素占比可判定启动台是否在画面。"""
    white = 0
    total = 0
    for yy in range(y, y + h, 3):
        for xx in range(x, x + w, 3):
            i = (yy * W + xx) * 4
            if buf[i] > 200 and buf[i + 1] > 200 and buf[i + 2] > 200:
                white += 1
            total += 1
    return white / max(total, 1)


def noise_tiles(buf, W, H, x0, y0, x1, y1, tile=64, step=32, thresh=0.08):
    """在指定区域里找「逐像素随机彩色」的瓦片。

    判据（两关，缺一不可）：
      1. 该像素与左邻/上邻的 RGB 距离之和 > 140，且饱和度 > 70；
      2. **相邻像素的梯度方向不一致**——真随机噪点里，水平梯度与垂直梯度
         的符号关系是乱的；平滑渐变（照片花瓣、App Store 蓝标）虽然
         也有大色差，但梯度方向高度一致。

    第 2 条是必须的：第一版判据只用了第 1 条，把「照片」「App Store」
    这类平滑多彩图标全判成了噪点（2026-10-25 实测误报）。
    """
    hits = []
    for y in range(y0, min(y1, H - tile), step):
        for x in range(x0, min(x1, W - tile), step):
            hit = 0
            total = 0
            for yy in range(y + 1, y + tile - 1):
                for xx in range(x + 1, x + tile - 1):
                    i = (yy * W + xx) * 4
                    r, g, b = buf[i], buf[i + 1], buf[i + 2]
                    il = (yy * W + xx - 1) * 4
                    iu = (yy * W + xx - W) * 4
                    dh = (r - buf[il]) + (g - buf[il + 1]) + (b - buf[il + 2])
                    dv = (r - buf[iu]) + (g - buf[iu + 1]) + (b - buf[iu + 2])
                    d = abs(dh) + abs(dv)
                    mx, mn = max(r, g, b), min(r, g, b)
                    total += 1
                    if d > 140 and mx - mn > 70:
                        # 梯度方向一致性：同号说明是平滑渐变，异号才可能是噪点
                        if (dh > 0) != (dv > 0) or dh == 0 or dv == 0:
                            hit += 1
            if total and hit / total > thresh:
                hits.append((x, y, hit / total))
    return hits


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "build/verify/launchpad_check"
    os.makedirs(outdir, exist_ok=True)

    subprocess.run(["open", "-a", "/System/Applications/Apps.app"], capture_output=True)

    frames = []
    for i in range(8):
        time.sleep(0.45)
        p = os.path.join(outdir, "frame_%02d.png" % i)
        if grab(p):
            frames.append(p)

    if not frames:
        print("❌ 一帧都没抓到")
        return 1

    best = None
    print("=== 各帧的启动台可见性 ===")
    for p in frames:
        W, H, buf = read_png_rgba(p)
        ratio = tab_bar_white_ratio(buf, W, *LAUNCHPAD_BOX)
        ok = ratio > 0.06
        print("  %-16s tab栏白像素 %.1f%%  %s" % (os.path.basename(p), ratio * 100,
                                                "启动台可见" if ok else "-"))
        if ok and (best is None or ratio > best[1]):
            best = (p, ratio, W, H, buf)

    if best is None:
        print("❌ 8 帧里都没抓到启动台（焦点一直被抢）")
        print("   建议：手动点一下桌面空白处再运行，或先关掉会抢焦点的窗口")
        return 2

    path, ratio, W, H, buf = best
    print()
    print("✅ 采用帧：%s（tab栏白像素 %.1f%%）" % (os.path.basename(path), ratio * 100))

    x, y, w, h = ICON_ROW
    hits = noise_tiles(buf, W, H, x, y, x + w, y + h)
    print()
    print("=== 启动台图标区噪点扫描 ===")
    print("  区域 (%d,%d) %dx%d" % (x, y, w, h))
    if hits:
        xs = [p[0] for p in hits]
        ys = [p[1] for p in hits]
        print("  ❌ 发现 %d 个噪点瓦片" % len(hits))
        for hx, hy, f in hits[:12]:
            print("     @(x=%d y=%d) 噪点占比 %.0f%%" % (hx, hy, f * 100))
        print("  包围盒: x %d..%d, y %d..%d" % (min(xs), max(xs) + 64, min(ys), max(ys) + 64))
        crop_zoom(path, os.path.join(outdir, "bad_area.png"),
                  min(xs), min(ys), min(max(xs) + 64 - min(xs), 400),
                  min(max(ys) + 64 - min(ys), 400), 2)
        print("  已裁出坏图区域 → %s/bad_area.png" % outdir)
        return 3
    else:
        print("  ✅ 该区域内没有噪点瓦片")
        crop_zoom(path, os.path.join(outdir, "icons.png"), x, y, w, h, 1)
        print("  已裁出图标区 → %s/icons.png" % outdir)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
