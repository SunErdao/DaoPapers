"""从精细化 SVG 生成完整 macOS 图标集 + 菜单栏图标。

流程：
  app-icon.svg  →  WebKit 逐尺寸渲染  →  AppIcon.iconset/  →  自组装 →  AppIcon.icns
  app-icon.svg  →  22pt 菜单栏版（满色）
  app-icon.svg  →  22pt 菜单栏版（白版/单色，供模板图使用）

每个尺寸都是**原生渲染**（重新光栅化），不是缩放，小尺寸不糊。
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ASSETS = os.path.join(ROOT, "assets")
SVG = os.path.join(ASSETS, "app-icon.svg")
TRAY = os.path.join(ASSETS, "tray")

sys.path.insert(0, HERE)
from render_svg import render  # noqa: E402
from strip_png_chunks import strip_chunks  # noqa: E402

# macOS iconset 规格：文件名 = 逻辑尺寸 @ 倍率
ICONSET_MAP = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]


def build_iconset(force=False):
    """逐尺寸渲染到 iconset。

    不预先 rmtree 整个目录——沙箱禁止删除既有文件，
    直接覆盖写入即可（打包只读目录里的固定文件名）。

    force=False 时做**新鲜度判断**：SVG 比 iconset 里的成品旧就整批跳过，
    省掉每次 install 都要重渲染 10 个尺寸的 4 分钟。
    """
    iconset = os.path.join(ASSETS, "AppIcon.iconset")
    os.makedirs(iconset, exist_ok=True)
    if not force:
        svg_mtime = os.path.getmtime(SVG)
        outputs = [os.path.join(iconset, n) for _, n in ICONSET_MAP]
        if all(os.path.exists(p) for p in outputs) and \
                min(os.path.getmtime(p) for p in outputs) > svg_mtime:
            # 即便跳过渲染，也要确认产物里没有 eXIf（否则 IconServices 会拒收）
            for p in outputs:
                strip_chunks(p)
            print("  iconset 已是当前 SVG 的产物，跳过重渲染"
                  "（改 SVG 或加 --force 强制重建）")
            return iconset
    for px, name in ICONSET_MAP:
        out = os.path.join(iconset, name)
        render(SVG, out, px)
        # 关键：WebKit 快照会带 eXIf chunk，IconServices 不认 → 整张 icns 被拒
        # → 回退「通用应用占位图标」。必须在渲染后立刻剥掉。
        strip_chunks(out)
        print(f"  {name:24s} {px}x{px}")
    return iconset


def build_icns(iconset):
    """打包 icns。

    **主路：自组装（scripts/build/build_icns.py）——只产 PNG 型图层。**

    为什么不用 iconutil 做主路（2026-10-25 实测）：
    iconutil 除了 PNG 层，还会额外产 legacy ARGB / 调色板索引图层
    （ic04 / ic05）。它们是「调色板索引」格式，实测我方 SVG 渲染出的
    ic05 调色板色数高达 618/1282，远超 8 位索引上限 256 →
    小尺寸场景（Launchpad 应用库、窗口标题栏左上角代理图标）优先取
    legacy 层 → **直接显示彩色噪点**（用户实测截图确认）。

    iconutil 现在只作兜底（自组装失败时用），且其产物必须过 verify()
    的 legacy 禁令校验——不过就报错，不允许静默装进 App。

    另：iconutil 在本机需要项目内的 TMPDIR（沙箱不允许写系统临时目录）。
    """
    import build_icns as icns_builder

    out = os.path.join(ASSETS, "AppIcon.icns")
    tmpdir = os.path.join(ROOT, "build", "tmp")
    os.makedirs(tmpdir, exist_ok=True)

    method = ""
    try:
        n, cnt = icns_builder.build(iconset=iconset, out=out)
        method = "自组装（纯 PNG 型图层）"
    except Exception as exc:
        print(f"  自组装失败（{exc}），回退 iconutil")
        tmp_icns = os.path.join(tmpdir, "AppIcon.icns")
        # iconutil 要求输出扩展名必须是 .icns
        if os.path.exists(tmp_icns):
            os.unlink(tmp_icns)
        env = dict(os.environ, TMPDIR=tmpdir)
        proc = subprocess.run(
            ["iconutil", "-c", "icns", iconset, "-o", tmp_icns],
            capture_output=True, env=env)
        if proc.returncode != 0 or not os.path.exists(tmp_icns):
            raise RuntimeError(
                f"iconutil 也失败：{proc.stderr.decode('utf-8', 'ignore')[:200]}")
        shutil.copyfile(tmp_icns, out)   # 纯覆盖写入，沙箱允许
        method = "iconutil（兜底）"

    ok, info = icns_builder.verify(out)
    if not ok:
        raise RuntimeError(f"icns 校验失败：{info}")
    return out, os.path.getsize(out), len(info), method, info


def build_tray():
    """满色菜单栏图标（与 App 图标同一套图形）。

    白版剪影由 scripts/build/gen_tray_white.py 单独生成（需要单独设计，
    不能靠把满色版所有色标替换为白色——三层浪会糊成一坨实心块）。
    """
    os.makedirs(TRAY, exist_ok=True)
    render(SVG, os.path.join(TRAY, "appicon.png"), 22)
    render(SVG, os.path.join(TRAY, "appicon@2x.png"), 44)
    print("  满色 22pt / 44px")


def main():
    force = "--force" in sys.argv
    print("渲染 iconset：")
    iconset = build_iconset(force=force)
    icns, n, cnt, method, info = build_icns(iconset)
    print(f"\nicns: {icns}（{n:,} bytes，{cnt} 个 chunk，打包方式：{method}）")
    for t, sz, dim in info:
        print(f"  {t:6s} {sz:>9,} bytes  {dim}")

    # 1024 主图（便于交付与预览）
    main1024 = os.path.join(ASSETS, "AppIcon-1024.png")
    if force or not os.path.exists(main1024) or \
            os.path.getmtime(main1024) < os.path.getmtime(SVG):
        render(SVG, main1024, 1024)
    print(f"1024 主图: {main1024}")

    print("\n渲染菜单栏图标：")
    build_tray()


if __name__ == "__main__":
    main()
