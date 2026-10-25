"""菜单栏托盘：常驻入口，提供上一张/下一张/收藏/保存/屏蔽等快捷操作。

注意：本类是 NSObject 子类，方法名必须符合 selector 规范（下划线 = 冒号参数）。
"""

from __future__ import annotations

import os

import objc
from AppKit import (
    NSImage,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSMakeSize

from ..logger import get as log

# 图标资源与可选值
#   white：纯白单色剪影（模板图，系统按菜单栏明暗自动反成白/黑）——
#          与 WorkBuddy 状态栏图标同一套规范，是菜单栏的标准做法
#   appicon：满色应用图标（与应用图标/Dock/启动台完全同一套图形）
#   glyph / solid：旧版单色剪影（模板图，跟随系统明暗）
STYLES = ("white", "appicon", "glyph", "solid")
COLORS = ("auto", "white", "black", "gray")


def _asset_path(root: str, style: str, color: str):
    """优先取 @2x（44px 像素、22pt 尺寸，Retina 下清晰且与系统图标等大）。"""
    folder = os.path.join(root, "assets", "tray")
    for suffix in ("@2x.png", ".png"):
        path = os.path.join(folder, f"{style}_{color}{suffix}")
        if os.path.exists(path):
            return path
    return None


def _simple_path(root: str, stem: str):
    """取 assets/tray/<stem>@2x.png，没有则退回 <stem>.png。"""
    folder = os.path.join(root, "assets", "tray")
    for name in (f"{stem}@2x.png", f"{stem}.png"):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    return None


def _sub_item(menu, title, payload, target):
    """普通函数（非 NSObject 方法），避免 selector 命名约束。"""
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "setTrayIcon:", "")
    item.setTarget_(target)
    item.setRepresentedObject_(payload)
    menu.addItem_(item)
    return item


class Tray(NSObject):
    def initWithApp_(self, app):
        self = objc.super(Tray, self).init()
        if self is None:
            return None
        self.app = app
        self.item = None
        self.menu = None
        return self

    def build(self):
        status = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.item = status
        self.apply_icon()

        menu = NSMenu.alloc().init()
        menu.setDelegate_(self)
        status.setMenu_(menu)
        self.menu = menu
        self.rebuild()

        # 布局稳定后自检：确认图标真的落进了菜单栏（而不是只有 API 调用成功）
        self._frame_checks = 0
        self.performSelector_withObject_afterDelay_("reportFrame:", None, 2.0)
        return status

    def reportFrame_(self, _obj):
        """状态项自检。若窗口高度为 0，说明系统没有把它布置进菜单栏
        （某些非 Aqua 会话的启动上下文会这样），重试几次后改为主窗口入口。"""
        self._frame_checks = getattr(self, "_frame_checks", 0) + 1
        try:
            button = self.item.button()
            win = button.window() if button is not None else None
            if win is None:
                log().warning("状态栏自检：按钮没有窗口")
                ok = False
            else:
                f = win.frame()
                ok = f.size.height > 1.0
                log().info(
                    "状态栏自检：图标窗口 x=%.0f y=%.0f，尺寸 %.0fx%.0f，菜单栏厚度 %.0f",
                    f.origin.x, f.origin.y, f.size.width, f.size.height,
                    NSStatusBar.systemStatusBar().thickness(),
                )
            if ok or self._frame_checks >= 3:
                if not ok:
                    log().warning("菜单栏图标未能就绪，改为主窗口入口")
                    self.app.show_window("today")
                return
            # 还没布置好，稍后再看一次
            self.performSelector_withObject_afterDelay_("reportFrame:", None, 3.0)
        except Exception as exc:
            log().warning("状态栏自检失败：%s", exc)

    # ---------------- 图标 ---------------- #
    def apply_icon(self):
        """按配置装载菜单栏图标：尺寸默认 22pt，与系统图标等大。

        style=white   → 纯白单色剪影，设为模板图由系统自动反色（菜单栏标准做法）
        style=appicon → 直接用满色应用图标（与 Dock / 启动台同一张图）
        style=glyph/solid → 旧版单色剪影（模板图，跟随系统明暗反色）
        """
        if self.item is None:
            return
        button = self.item.button()
        cfg = self.app.cfg

        style = str(cfg.get("display.tray_icon_style", "white")).lower()
        if style not in STYLES:
            style = "white"
        color = str(cfg.get("display.tray_icon_color", "auto")).lower()
        if color not in COLORS:
            color = "auto"
        try:
            size = float(cfg.get("display.tray_icon_size", 22) or 22)
        except (TypeError, ValueError):
            size = 22.0
        size = max(12.0, min(22.0, size))

        if style == "appicon":
            # 满色应用图标：不是模板图，系统不会反色
            path = _simple_path(self.app.root, "appicon")
            icon = NSImage.alloc().initWithContentsOfFile_(path) if path else None
            is_template = False
            if icon is None:
                log().warning("未找到满色应用图标资源：%s", path)
        elif style == "white":
            # 纯白剪影：模板图，系统在深色菜单栏显示为白、浅色菜单栏显示为黑
            path = _simple_path(self.app.root, "white")
            icon = NSImage.alloc().initWithContentsOfFile_(path) if path else None
            is_template = True
            if icon is None:
                log().warning("未找到白版剪影资源：%s", path)
        else:
            is_template = color == "auto"
            path = _asset_path(self.app.root, style, "black" if is_template else color)
            icon = NSImage.alloc().initWithContentsOfFile_(path) if path else None

        if icon is None:
            # 资源缺失时退回系统符号，但必须显式给尺寸（否则默认 18x14 会显得小）
            icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_("photo", "岛·壁纸")
            is_template = True

        if icon is not None:
            icon.setSize_(NSMakeSize(size, size))
            icon.setTemplate_(is_template)
            button.setImage_(icon)
            button.setTitle_("")
            if style == "white":
                desc = "纯白剪影·模板图自动反色"
            elif style == "appicon":
                desc = "满色·与应用图标一致"
            else:
                desc = "模板图·跟随系统明暗" if is_template else "固色图"
            log().info("菜单栏图标：%s %.0fpt（%s）", style, size, desc)
            self._audit_icon(icon, style, is_template)
        else:
            button.setTitle_("壁")
            log().warning("未找到菜单栏图标资源，退回文字「壁」")
        button.setToolTip_("岛·壁纸")

    def _audit_icon(self, icon, style: str, is_template: bool) -> None:
        """运行时自检：把「实际挂到按钮上的图像」的关键属性写进日志。

        菜单栏的最终合成层受系统保护、截不到像素，所以这里改为在 App 进程内
        核对按钮上真实图像的对象属性——这是能拿到的最接近真相的证据。
        """
        try:
            reps = icon.representations()
            rep = reps[0] if reps else None
            px = ""
            if rep is not None and rep.pixelsWide() > 0:
                c = rep.colorAtX_y_(rep.pixelsWide() // 2, rep.pixelsHigh() // 2)
                px = f"，中心像素 rgb({c.redComponent():.2f},{c.greenComponent():.2f},{c.blueComponent():.2f})"
            log().info(
                "菜单栏图标自检：尺寸 %.0fx%.0f pt，背衬 %dx%d px，模板图=%s%s",
                icon.size().width,
                icon.size().height,
                rep.pixelsWide() if rep is not None else 0,
                rep.pixelsHigh() if rep is not None else 0,
                "是" if is_template else "否（满色）",
                px,
            )
        except Exception as exc:
            log().warning("菜单栏图标自检失败：%s", exc)

    # ---------------- NSMenuDelegate ---------------- #
    def menuWillOpen_(self, menu):
        try:
            self.rebuild()
        except Exception as exc:
            log().warning("重建托盘菜单失败：%s", exc)

    def rebuild(self):
        if self.menu is None:
            return
        self.menu.removeAllItems()
        app = self.app

        self.addItemWithTitle_action_("显示今日壁纸…", "showWindow:")
        self.addSep()

        title = app.current_title() or "还没有壁纸"
        self.addItemWithTitle_action_(f"当前：{title}", "").setEnabled_(False)

        self.addItemWithTitle_action_("下一张", "nextPhoto:")
        self.addItemWithTitle_action_("上一张", "prevPhoto:")
        self.addItemWithTitle_action_("换一张新图", "refreshPhoto:")
        self.addSep()

        label = "取消收藏" if app.is_favorite() else "收藏这张"
        self.addItemWithTitle_action_(label, "toggleFavorite:")
        self.addItemWithTitle_action_("保存到本地…", "savePhoto:")
        self.addItemWithTitle_action_("不感兴趣，屏蔽此图", "blockPhoto:")
        self.addSep()

        self.menu.addItem_(self.iconSubmenu())
        self.addItemWithTitle_action_("设置…", "openSettings:")
        self.addItemWithTitle_action_("打开配置文件", "openConfigFile:")
        self.addItemWithTitle_action_("重新载入配置", "reloadConfig:")
        self.addSep()

        self.addItemWithTitle_action_(f"下次更新：{app.next_fire_hint()}", "").setEnabled_(False)
        self.addSep()
        self.addItemWithTitle_action_("退出", "quitApp:")

    def iconSubmenu(self):
        cfg = self.app.cfg
        cur_color = str(cfg.get("display.tray_icon_color", "auto")).lower()
        cur_style = str(cfg.get("display.tray_icon_style", "white")).lower()
        target = self.app.menu_target()

        sub_menu = NSMenu.alloc().init()
        for key, label in (
            ("white", "白版剪影（推荐）"),
            ("appicon", "应用图标（满色）"),
            ("glyph", "纯图形（单色）"),
            ("solid", "实心圆角（单色）"),
        ):
            _sub_item(sub_menu, label, f"style:{key}", target).setState_(
                1 if cur_style == key else 0
            )
        sub_menu.addItem_(NSMenuItem.separatorItem())
        for key, label in (
            ("auto", "跟随系统明暗"),
            ("white", "纯白"),
            ("black", "纯黑"),
            ("gray", "灰色"),
        ):
            _sub_item(sub_menu, label, f"color:{key}", target).setState_(
                1 if cur_color == key else 0
            )

        parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("菜单栏图标", None, "")
        parent.setSubmenu_(sub_menu)
        return parent

    def addItemWithTitle_action_(self, title, action):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action or "", "")
        if action:
            item.setTarget_(self.app.menu_target())
        self.menu.addItem_(item)
        return item

    def addSep(self):
        self.menu.addItem_(NSMenuItem.separatorItem())
