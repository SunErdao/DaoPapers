"""应用装配：把配置、引擎、调度器、菜单栏和窗口接在一起，并驱动 AppKit 主循环。

约定：只有需要被 AppKit 回调的对象（菜单目标、主线程任务）才继承 NSObject，
其余一律是普通 Python 类，避免 selector 命名约束。
"""

from __future__ import annotations

import json
import os
import threading

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSObject,
    NSWorkspace,
)
from Foundation import NSURL

from . import __version__, server
from .config import Config
from .engine import Engine
from .logger import get as log, setup as setup_log
from .mainthread import run_on_main
from .scheduler import Scheduler
from .ui import Api, MainWindow, Tray


# --------------------------------------------------------------------------- #
# 菜单栏点击目标
# --------------------------------------------------------------------------- #
class MenuActions(NSObject, protocols=[objc.protocolNamed("NSApplicationDelegate")]):
    def initWithOwner_(self, owner):
        self = objc.super(MenuActions, self).init()
        if self is None:
            return None
        self.owner = owner
        self._shown_once = False  # 首启后仅自动弹窗一次
        return self

    def showWindow_(self, sender):
        self.owner.show_window("today")

    def openSettings_(self, sender):
        self.owner.show_window("settings")

    def nextPhoto_(self, sender):
        self.owner.spawn(lambda: self.owner.engine.goto(1))

    def prevPhoto_(self, sender):
        self.owner.spawn(lambda: self.owner.engine.goto(-1))

    def refreshPhoto_(self, sender):
        self.owner.spawn(lambda: self.owner.engine.refresh(force_new=True))

    def toggleFavorite_(self, sender):
        self.owner.spawn(lambda: self.owner.engine.favorite_current())

    def savePhoto_(self, sender):
        try:
            self.owner.api.do_save({})
        except Exception as exc:
            log().warning("保存失败：%s", exc)

    def blockPhoto_(self, sender):
        self.owner.spawn(lambda: self.owner.engine.block_current(block_author=False))

    def openConfigFile_(self, sender):
        self.owner.open_config_file()

    def reloadConfig_(self, sender):
        self.owner.engine.reload()
        self.owner.restart_scheduler()
        self.owner.refresh_tray_icon()
        log().info("配置已重新载入")

    def pollActivate_(self, timer):
        """从启动台/Finder 再次打开时，唤起主窗口（保持单实例）。"""
        path = os.path.join(self.owner.root, "data", ".activate")
        if not os.path.exists(path):
            return
        try:
            os.unlink(path)
        except OSError:
            pass
        log().info("收到唤起请求，显示主窗口")
        self.owner.show_window("today")

    def setTrayIcon_(self, sender):
        """切换菜单栏图标：payload 形如 color:white / style:solid。"""
        try:
            payload = str(sender.representedObject() or "")
            kind, _, value = payload.partition(":")
            if kind not in ("color", "style") or not value:
                return
            key = "display.tray_icon_color" if kind == "color" else "display.tray_icon_style"
            self.owner.cfg.save_updates({key: value})
            self.owner.refresh_tray_icon()
            log().info("菜单栏图标已切换：%s", payload)
        except Exception as exc:
            log().warning("切换菜单栏图标失败：%s", exc)
        finally:
            try:
                self.owner.tray.rebuild()
            except Exception:
                pass

    def quitApp_(self, sender):
        NSApp.terminate_(None)

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag):
        """启动台 / Dock 点击已运行的应用时，系统发来 reopen 事件。

        此前没有 delegate，辅助型应用对 reopen 默认无动作，于是「点了没反应」。
        这里直接把主窗口唤到前台（已存在则置顶 / 取消最小化）。
        """
        log().info("收到系统唤起（reopen），显示主窗口")
        self.owner.show_window("today")
        return True

    def applicationDidBecomeActive_(self, notification):
        """App 完全激活后首次自动弹出主窗口（冷启动场景）。

        首启窗口若放在 applicationDidFinishLaunching_ 里，App 尚处于启动激活的
        过渡期，activateIgnoringOtherApps_ 会被忽略 → 窗口上屏不稳（实测首启后
        几秒内查不到 on-screen 窗口）。放到 becomeActive 回调、App 已完全激活时
        再弹，与已运行时的 reopen 走同一条已验证的 show_window 路径，稳定可靠。
        仅首启自动弹一次；之后由菜单 / reopen 处理器控制。
        """
        if self._shown_once:
            return
        self._shown_once = True
        log().info("首启后 App 已激活，显示主窗口")
        self.owner.show_window("today")


# --------------------------------------------------------------------------- #
class Application:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.cfg: Config = None
        self.engine: Engine = None
        self.scheduler: Scheduler = None
        self.tray: Tray = None
        self.window: MainWindow = None
        self.api: Api = None
        self.base_url = ""
        self._port = None
        self._httpd = None
        self._actions = None

    # ---------------- 装配 ---------------- #
    def setup(self) -> None:
        self.cfg = Config.load(self.root)
        setup_log(self.cfg.log_dir, level=str(self.cfg.get("ui.log_level", "INFO")))
        log().info("岛·壁纸 v%s 启动（配置：%s）", __version__, self.cfg.path)

        self.engine = Engine(self.cfg)
        self.engine.add_listener(self.on_engine_event)
        self.api = Api(self)
        self._actions = MenuActions.alloc().initWithOwner_(self)

        self.base_url, self._port, self._httpd = server.start(self.root)
        log().info("本地界面服务：%s", self.base_url)

        self.tray = Tray.alloc().initWithApp_(self)
        self.tray.build()

        # 每秒检查一次「唤起」请求：从启动台/Finder 再次打开时显示窗口
        from Foundation import NSTimer

        self._activate_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self._actions, "pollActivate:", None, True
        )

        self.start_scheduler()
        threading.Thread(target=self.startup_task, name="startup", daemon=True).start()

    def menu_target(self):
        return self._actions

    def refresh_tray_icon(self) -> None:
        """按当前配置重绘菜单栏图标（颜色 / 样式 / 尺寸）。"""
        if self.tray is not None:
            self.tray.apply_icon()

    def startup_task(self) -> None:
        try:
            self.engine.startup()
        except Exception as exc:
            log().warning("启动换图失败：%s", exc)
        finally:
            self.push_state()

    # ---------------- 调度 ---------------- #
    def start_scheduler(self) -> None:
        self.scheduler = Scheduler(
            get_times=lambda: self.cfg.schedule_times,
            get_interval=lambda: self.cfg.interval_minutes,
            on_tick=self.on_schedule_tick,
            check_seconds=30,
        )
        self.scheduler.start()

    def restart_scheduler(self) -> None:
        if self.scheduler:
            self.scheduler.stop()
        self.start_scheduler()

    def on_schedule_tick(self, reason: str) -> None:
        log().info("定时触发换图（%s）", reason)
        self.spawn(lambda: self.engine.refresh(force_new=True))

    # ---------------- 事件与状态推送 ---------------- #
    def on_engine_event(self, event: str, data: dict) -> None:
        if event == "changed":
            self.push_state()

    def push_state(self) -> None:
        def job():
            if self.window is None or self.window.web is None:
                return
            try:
                self.window.push("state", self.engine.state())
            except Exception as exc:
                log().warning("推送状态失败：%s", exc)

        run_on_main(job)

    # ---------------- 窗口 ---------------- #
    def ensure_window(self) -> MainWindow:
        if self.window is None:
            url = f"{self.base_url}/ui/index.html"
            self.window = MainWindow(
                url,
                int(self.cfg.get("ui.window_width", 1180)),
                int(self.cfg.get("ui.window_height", 780)),
                "岛·壁纸",
                self.on_web_message,
            )
            self.window.build()
        return self.window

    def on_web_message(self, payload: dict) -> None:
        ok, result = self.api.handle(payload)
        if self.window is None or self.window.web is None:
            return
        rid = str(payload.get("id") or "")
        data = result if ok else {"error": result}
        js = f"window.__resolve({json.dumps(rid)}, {'true' if ok else 'false'}, {json.dumps(data, ensure_ascii=False)});"
        try:
            self.window.web.evaluateJavaScript_completionHandler_(js, None)
        except Exception as exc:
            log().warning("回传结果失败：%s", exc)

    def show_window(self, view: str = "today") -> None:
        def job():
            win = self.ensure_window()
            win.show()
            if view != "today":
                win.push("navigate", {"view": view})
            self.push_state()

        run_on_main(job)

    # ---------------- 供托盘读取的信息 ---------------- #
    def current_title(self) -> str:
        cur = self.engine.store.current
        if not cur:
            return ""
        title = cur.photo.title or ""
        return title if len(title) <= 28 else title[:27] + "…"

    def is_favorite(self) -> bool:
        cur = self.engine.store.current
        return bool(cur and self.engine.store.is_favorite(cur.key()))

    def next_fire_hint(self) -> str:
        return self.scheduler.next_fire_hint() if self.scheduler else "未设置"

    # ---------------- 工具 ---------------- #
    def spawn(self, fn) -> None:
        def work():
            try:
                fn()
            except Exception as exc:
                log().warning("操作失败：%s", exc)
            finally:
                self.push_state()

        threading.Thread(target=work, daemon=True).start()

    def open_url(self, url: str) -> None:
        if url.startswith("file://"):
            NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
                [NSURL.URLWithString_(url)]
            )
            return
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    def open_config_file(self) -> None:
        ws = NSWorkspace.sharedWorkspace()
        if not ws.openFile_(self.cfg.path):
            try:
                import subprocess

                subprocess.Popen(["open", "-e", self.cfg.path])
            except OSError:
                log().warning("无法打开配置文件：%s", self.cfg.path)

    def quit(self) -> None:
        NSApp.terminate_(None)


# --------------------------------------------------------------------------- #
def _load_bundle_icon():
    """从 bundle 的 AppIcon.icns 加载应用图标；失败返回 None（不阻断启动）。"""
    try:
        from AppKit import NSBundle, NSImage

        bundle = NSBundle.mainBundle()
        if bundle is None:
            return None
        res = bundle.resourcePath()
        if not res:
            return None
        path = os.path.join(res, "AppIcon.icns")
        if not os.path.exists(path):
            return None
        return NSImage.alloc().initWithContentsOfFile_(path)
    except Exception:
        return None


def _dump_runtime_icon(app_ns, outdir):
    """把「实际上报给系统的应用图标」落盘，供逐档位比对。

    必须在 App 自己的进程里跑：独立进程里 NSApp.applicationIconImage()
    拿到的永远是系统通用占位图（蓝色文件夹），因为那个进程从未上报过图标。
    """
    from AppKit import NSBitmapImageFileTypePNG, NSBitmapImageRep, NSGraphicsContext, NSImage

    os.makedirs(outdir, exist_ok=True)

    def _write(rep, name):
        try:
            data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
            if data is None:
                print("dump: %s 无法编码 PNG" % name)
                return
            path = os.path.join(outdir, name)
            # atomically=False：直接写盘，不走临时文件（沙箱里 tempfile 不可用）
            data.writeToFile_atomically_(path, False)
            print("dump: %s -> %d bytes" % (name, data.length()))
        except Exception as exc:
            print("dump: %s 失败：%s" % (name, exc))

    img = app_ns.applicationIconImage()
    if img is None:
        print("dump: applicationIconImage() 为 None")
        return

    reps = list(img.representations())
    print("dump: 上报图标 size=%s representations=%d" % (img.size(), len(reps)))
    for i, rep in enumerate(reps):
        print("  rep[%d] %s pixels=%sx%s points=%s" % (
            i, rep.className(), rep.pixelsWide(), rep.pixelsHigh(), rep.size()))

    # 逐个 representation 单独落盘：能看出「是哪一层坏了」
    for i, rep in enumerate(reps):
        try:
            single = NSImage.alloc().initWithSize_(rep.size())
            single.addRepresentation_(rep)
            _write(single, "rep_%02d.png" % i)
        except Exception as exc:
            print("dump: rep[%d] 包装失败：%s" % (i, exc))

    # 整图按多档尺寸渲染落盘：与 NSImage 直接渲染（nsimg_all.png）逐档比对
    for px in (16, 32, 64, 128, 256):
        try:
            rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
                None, px, px, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0)
            ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.setCurrentContext_(ctx)
            # 只用单参数 drawInRect_：多参数重载会丢源矩形（画出来是空白）
            img.drawInRect_(((0, 0), (px, px)))
            NSGraphicsContext.restoreGraphicsState()
            _write(rep, "appicon_%d.png" % px)
        except Exception as exc:
            print("dump: %dpx 渲染失败：%s" % (px, exc))


def run(root: str, once: bool = False, open_window: bool = False) -> int:
    if once:
        cfg = Config.load(root)
        setup_log(cfg.log_dir)
        engine = Engine(cfg)
        entry = engine.refresh(force_new=True)
        if entry:
            print(f"已设置壁纸：{entry.photo.title}")
            print(f"本地文件：{entry.file}")
            return 0
        print("换图失败，详情见日志：" + os.path.join(cfg.log_dir, "app.log"))
        return 1

    app_ns = NSApplication.sharedApplication()
    # 常规应用（有 Dock 图标）：启动台 / Dock 点击都能正常唤起，符合用户习惯。
    # 旧版用 Accessory（无 Dock 图标），导致 Dock 里没有图块可点、且 reopen 无响应。
    app_ns.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    # 显式设置应用图标：Dock / 菜单栏用的默认图标来自「进程启动时的 bundle 快照」，
    # 换图标后不重装就仍是旧图（用户实测：Dock 图标没跟着换）。
    # 这里从 bundle 的 AppIcon.icns 重新加载，保证运行中的图标是新图。
    _icon = _load_bundle_icon()
    if _icon is not None:
        try:
            app_ns.setApplicationIconImage_(_icon)
        except Exception:
            pass
    # 诊断钩子：DAOPAPERS_DUMP_ICON=<目录> 时，把「实际上报给系统的图标」
    # 在 App 自己的进程里落盘。必须在 App 进程内跑——独立进程拿到的
    # NSApp.applicationIconImage() 是通用占位图，不是我们上报的那张。
    if os.environ.get("DAOPAPERS_DUMP_ICON"):
        try:
            _dump_runtime_icon(app_ns, os.environ["DAOPAPERS_DUMP_ICON"])
        except Exception as exc:  # 诊断代码不得影响正常启动
            log().warning("图标诊断 dump 失败：%s", exc)
    application = Application(root)
    application.setup()
    # 让 AppKit 的 reopen / 激活事件有处理器（解决「点了没反应」）
    app_ns.setDelegate_(application._actions)
    # 首启弹窗交给 applicationDidFinishLaunching_ 处理（App 已激活时），
    # 与已运行时的 reopen 行为保持一致：冷启动也是点一下就出窗口。
    app_ns.run()
    return 0
