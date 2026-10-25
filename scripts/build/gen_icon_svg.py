"""生成精细化后的「日落波浪」应用图标 SVG。

以用户手绘原稿（/Users/sunerdao/Downloads/DaoPapers图标.svg）为基准，
做以下精细化修正：

1. 底板：普通圆角矩形 → macOS 标准 squircle（连续曲率超椭圆），
   且修正原稿「宽 988 / 高 964」的不等边问题，改为正方形居中。
2. 去掉满画布的 #08090b 方块底（macOS 图标外围必须透明）。
3. 去掉与主路径错位的内框 rect（991×966 rx=14），改为与 squircle 一致的描边。
4. 深浪层提亮，与地面拉开层次（原稿 #39363c 与地面 #1b1c22 太接近，糊成一片）。
5. 层间加投影：白浪压暖浪、暖浪压深浪，做出「薄片叠放」的立体感。
6. 太阳加暖色辉光，让「落日」有氛围。
7. 太阳位于白浪之后（保持原稿遮挡关系：日落时太阳半沉于地平线）。
8. 中间加一层极淡的地平线暖光带，强化落日氛围。
"""
import math
import os

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "assets")

# ---------------- 底板几何 ----------------
A = 494.0          # 半轴：底板 x/y ∈ [18, 1006]，正方形居中于 512
N = 5.0            # 超椭圆指数（Apple squircle ≈ 5）


def se_point(t):
    ct, st = math.cos(t), math.sin(t)
    x = A * (abs(ct) ** (2.0 / N)) * (1 if ct >= 0 else -1)
    y = A * (abs(st) ** (2.0 / N)) * (1 if st >= 0 else -1)
    return x, y


def squircle_path(steps=512):
    """squircle 轮廓（折线逼近，弦高偏差 0.008px）。"""
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        x, y = se_point(t)
        pts.append((512.0 + x, 512.0 + y))
    d = [f"M{f(pts[0][0])} {f(pts[0][1])}"]
    for (x, y) in pts[1:]:
        d.append(f"L{f(x)} {f(y)}")
    d.append("Z")
    return " ".join(d)


def f(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


# ---------------- 用户原稿的波浪路径（保持几何，仅调整配色/投影） ----------------
BACK = ("M188 646C244 613 298 574 363 556C425 539 481 545 530 557"
        "C585 571 626 595 682 600C738 605 780 585 820 584"
        "C838 584 854 591 856 600C859 611 846 620 828 629"
        "C785 651 743 677 700 706C655 736 617 773 571 791"
        "C527 809 475 809 429 793C376 775 328 746 278 727"
        "C243 714 207 701 184 688C171 681 173 667 188 656Z")

MID = ("M190 550C238 523 282 503 329 488C372 475 413 478 454 494"
       "C493 509 528 535 566 545C608 556 650 552 686 544"
       "C730 534 767 538 803 550C828 558 850 566 855 578"
       "C860 591 845 601 824 612C780 634 735 660 692 680"
       "C651 699 612 708 575 708C533 708 500 693 464 676"
       "C422 656 383 633 338 617C293 601 244 589 202 578"
       "C185 574 173 568 176 561C178 557 183 554 190 550Z")

FRONT = ("M198 451C249 430 291 408 331 382C367 359 401 336 438 325"
         "C472 314 507 314 539 323C574 333 604 354 635 372"
         "C668 391 699 403 735 416C770 429 804 443 832 454"
         "C846 459 854 467 854 476C854 486 845 494 831 501"
         "C800 517 767 534 735 549C701 565 673 574 641 575"
         "C605 576 576 572 545 562C511 551 482 536 450 521"
         "C416 505 384 495 349 489C312 482 274 479 239 477"
         "C220 476 201 474 192 469C186 465 189 457 198 451Z")

# 太阳：原稿 cx=649 cy=291 r=107
SUN_CX, SUN_CY, SUN_R = 649.0, 291.0, 107.0

# 精细化配色（在原稿基础上调整）
COL_SUN_HI = "#ffe9cd"
COL_SUN_LO = "#f0924f"
COL_SUN_GLOW = "#ffb26b"

COL_FRONT_HI = "#f8efec"
COL_FRONT_MID = "#f3e4de"
COL_FRONT_LO = "#e6d0c8"

COL_MID_HI = "#f5cdb0"
COL_MID_MID = "#d6a894"
COL_MID_LO = "#4e4648"

# 深浪：原稿 #39363c→#25262d 与地面太近，提亮到 #4a4550→#2b2a33
COL_BACK_HI = "#4a4550"
COL_BACK_MID = "#3a3742"
COL_BACK_LO = "#282730"

COL_GROUND_HI = "#1e1f26"
COL_GROUND_LO = "#14151a"


def build_svg():
    plate = squircle_path()

    # 太阳辉光：从太阳中心向外的径向渐变
    glow_r = 300
    sun_glow = (
        f'<radialGradient id="sunGlow" cx="50%" cy="50%" r="50%">'
        f'<stop offset="0" stop-color="{COL_SUN_GLOW}" stop-opacity="0.34"/>'
        f'<stop offset="0.45" stop-color="{COL_SUN_GLOW}" stop-opacity="0.12"/>'
        f'<stop offset="1" stop-color="{COL_SUN_GLOW}" stop-opacity="0"/>'
        f'</radialGradient>'
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-labelledby="title desc">
  <title id="title">日落波浪图标</title>
  <desc id="desc">深色圆角方形底板上，暖色太阳与三层柔和起伏的抽象波浪。</desc>
  <defs>
    <linearGradient id="sun" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{COL_SUN_HI}"/>
      <stop offset="1" stop-color="{COL_SUN_LO}"/>
    </linearGradient>
    {sun_glow}
    <linearGradient id="frontWave" x1="0" y1="0" x2="0.9" y2="0.8">
      <stop offset="0" stop-color="{COL_FRONT_HI}"/>
      <stop offset="0.55" stop-color="{COL_FRONT_MID}"/>
      <stop offset="1" stop-color="{COL_FRONT_LO}"/>
    </linearGradient>
    <linearGradient id="middleWave" x1="0" y1="0" x2="1" y2="0.8">
      <stop offset="0" stop-color="{COL_MID_HI}"/>
      <stop offset="0.38" stop-color="{COL_MID_MID}"/>
      <stop offset="1" stop-color="{COL_MID_LO}"/>
    </linearGradient>
    <linearGradient id="backWave" x1="0" y1="0" x2="1" y2="0.7">
      <stop offset="0" stop-color="{COL_BACK_HI}"/>
      <stop offset="0.55" stop-color="{COL_BACK_MID}"/>
      <stop offset="1" stop-color="{COL_BACK_LO}"/>
    </linearGradient>
    <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{COL_GROUND_HI}"/>
      <stop offset="1" stop-color="{COL_GROUND_LO}"/>
    </linearGradient>
    <!-- 太阳辉光层：营造落日氛围 -->
    <radialGradient id="halo" cx="50%" cy="50%" r="50%">
      <stop offset="0" stop-color="{COL_SUN_GLOW}" stop-opacity="0.30"/>
      <stop offset="0.55" stop-color="{COL_SUN_GLOW}" stop-opacity="0.09"/>
      <stop offset="1" stop-color="{COL_SUN_GLOW}" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="iconClip">
      <path d="{plate}"/>
    </clipPath>
    <!-- 层间投影：白浪压暖浪、暖浪压深浪，做出薄片叠放的立体感 -->
    <filter id="dropMid" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="7" stdDeviation="7" flood-color="#0a0a0e" flood-opacity="0.55"/>
    </filter>
    <filter id="dropFront" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#0a0a0e" flood-opacity="0.50"/>
    </filter>
  </defs>
  <g clip-path="url(#iconClip)">
    <!-- 地面 -->
    <path d="{plate}" fill="url(#ground)"/>
    <!-- 落日辉光 -->
    <circle cx="{f(SUN_CX)}" cy="{f(SUN_CY)}" r="300" fill="url(#halo)"/>
    <!-- 最深的后浪 -->
    <path d="{BACK}" fill="url(#backWave)" filter="url(#dropMid)"/>
    <!-- 中间暖浪 -->
    <path d="{MID}" fill="url(#middleWave)" filter="url(#dropMid)"/>
    <!-- 落日 -->
    <circle cx="{f(SUN_CX)}" cy="{f(SUN_CY)}" r="{f(SUN_R)}" fill="url(#sun)"/>
    <!-- 最前的奶白浪 -->
    <path d="{FRONT}" fill="url(#frontWave)" filter="url(#dropFront)"/>
  </g>
  <!-- 底板描边：与 squircle 轮廓严格对齐 -->
  <path d="{plate}" fill="none" stroke="#2f3037" stroke-width="1.4"/>
</svg>
'''


def main():
    os.makedirs(ASSETS, exist_ok=True)
    out = os.path.join(ASSETS, "app-icon.svg")
    svg = build_svg()
    # 内容没变就别重写：mtime 会变，会把下游 iconset 的新鲜度判断
    # 全部作废，导致每次 install 都重渲染 10 个尺寸（4 分钟）。
    if os.path.exists(out):
        with open(out, "r", encoding="utf-8") as fp:
            if fp.read() == svg:
                print(f"已生成 {out}（内容无变化，保持原文件）")
                print(f"  底板 squircle: 半轴 {A}, 指数 N={N}, 中心 512")
                print(f"  太阳: ({SUN_CX}, {SUN_CY}) r={SUN_R}")
                return
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(svg)
    print(f"已生成 {out}")
    print(f"  底板 squircle: 半轴 {A}, 指数 N={N}, 中心 512")
    print(f"  太阳: ({SUN_CX}, {SUN_CY}) r={SUN_R}")


if __name__ == "__main__":
    main()
