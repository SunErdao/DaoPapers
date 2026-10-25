"""端到端验证：tray.apply_icon 在 appicon 模式下能正确装载满色图标。

用真实的 NSStatusItem（不落进菜单栏，只验证装载逻辑与图像属性）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from AppKit import NSStatusBar, NSVariableStatusItemLength  # noqa: E402

from app.ui.tray import Tray, _appicon_path, _asset_path  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeCfg:
    def __init__(self, d):
        self.d = d

    def get(self, k, default=None):
        return self.d.get(k, default)


class FakeApp:
    def __init__(self, d):
        self.root = ROOT
        self.cfg = FakeCfg(d)


def probe(cfg_dict, label):
    app = FakeApp(cfg_dict)
    status = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    tray = Tray.alloc().initWithApp_(app)
    tray.item = status
    tray.apply_icon()
    btn = status.button()
    img = btn.image()
    title = btn.title()
    print(f"[{label}]")
    print(f"  button.image = {img}")
    print(f"  image.size   = {img.size() if img else None}")
    print(f"  isTemplate   = {img.isTemplate() if img else None}")
    print(f"  button.title = {title!r}")
    print(f"  reps         = {[(r.pixelsWide(), r.pixelsHigh()) for r in img.representations()] if img else None}")
    # 抽一个中心像素，确认是满色（不是单色模板图）
    if img:
        rep = img.representations()[0]
        c = rep.colorAtX_y_(rep.pixelsWide() // 2, rep.pixelsHigh() // 2)
        print(f"  中心像素 RGB = ({c.redComponent():.2f}, {c.greenComponent():.2f}, {c.blueComponent():.2f})")
    print()


if __name__ == "__main__":
    print("资源路径检查：")
    print("  appicon →", _appicon_path(ROOT))
    print("  glyph_black →", _asset_path(ROOT, "glyph", "black"))
    print()

    probe({"display.tray_icon_style": "appicon",
           "display.tray_icon_color": "auto",
           "display.tray_icon_size": 22}, "style=appicon（新的默认值）")
    probe({"display.tray_icon_style": "solid",
           "display.tray_icon_color": "auto",
           "display.tray_icon_size": 22}, "style=solid（旧的单色模板图，回退可用）")
