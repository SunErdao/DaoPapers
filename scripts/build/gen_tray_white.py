"""生成菜单栏「白版」图标（单色模板图）。

参照规范来自 WorkBuddy 的实际做法：
  resources/trayTemplate@2x.png —— 44×44（22pt@2x）**纯 alpha 剪影**，
  实心单色、无渐变无描边，靠 alpha 定义形状，由系统按菜单栏明暗自动反色。
所以「白版」= 纯白实心剪影 + isTemplate=True，而不是彩色图标缩小。

形状设计（22pt 下必须可辨）：
  · 太阳：实心圆，位于右上
  · 波浪：一条**填充带**（有上下两条边，中间是实心），形成明确的水平色块
  · 只保留一条浪 + 一条较细的高浪，避免多条线在 22pt 下粘连成乱麻
  · 图形之间留出透明缝，形成清晰负形
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ASSETS = os.path.join(ROOT, "assets")
TRAY = os.path.join(ASSETS, "tray")

sys.path.insert(0, HERE)
from render_svg import render  # noqa: E402

# 太阳：实心圆，位于右上
SUN_CX, SUN_CY, SUN_R = 649.0, 250.0, 108.0

# 波浪：两道弧线（只取上缘），线宽保证 22pt 下约 1.7pt
# 设计坐标 → 实际 pt：线宽 / 740 * 22
WAVE_W = 58
WAVE1 = ("M205 470C262 443 306 418 350 392C392 368 432 348 472 340"
         "C508 333 544 340 578 357C614 375 648 400 686 414"
         "C722 427 762 440 800 452")
WAVE2 = ("M190 570C244 546 292 524 340 505C382 489 424 486 462 493"
         "C500 500 534 514 570 530C604 545 640 556 678 560"
         "C712 563 750 558 790 548")

# 画布裁到内容区（图形填满 22pt）
VB = "165 120 710 530"

WHITE_SVG = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{VB}">
  <!-- 菜单栏白版：纯白实心剪影（alpha 通道定义形状，系统自动反色） -->
  <circle cx="{SUN_CX}" cy="{SUN_CY}" r="{SUN_R}" fill="#ffffff"/>
  <g fill="none" stroke="#ffffff" stroke-width="{WAVE_W}"
     stroke-linecap="round" stroke-linejoin="round">
    <path d="{WAVE1}"/>
    <path d="{WAVE2}"/>
  </g>
</svg>
'''


def main():
    os.makedirs(TRAY, exist_ok=True)
    svg_out = os.path.join(TRAY, "white.svg")
    with open(svg_out, "w", encoding="utf-8") as fp:
        fp.write(WHITE_SVG)
    print(f"矢量源: {svg_out}")

    render(svg_out, os.path.join(TRAY, "white.png"), 22)
    render(svg_out, os.path.join(TRAY, "white@2x.png"), 44)
    print("渲染: white.png (22px) / white@2x.png (44px)")


if __name__ == "__main__":
    main()
