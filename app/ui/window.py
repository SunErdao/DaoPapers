"""主窗口：NSWindow + WKWebView，界面用 HTML/CSS 写，通过 JS 桥接调用本地能力。"""

from __future__ import annotations

import json

import objc
from AppKit import (
    NSApp,
    NSScreen,
    NSBackingStoreBuffered,
    NSColor,
    NSMakeRect,
    NSObject,
    NSURLRequest,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSURL
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

from ..logger import get as log

STYLE = (
    NSWindowStyleMaskTitled
    | NSWindowStyleMaskClosable
    | NSWindowStyleMaskMiniaturizable
    | NSWindowStyleMaskResizable
)


class ScriptHandler(NSObject, protocols=[objc.protocolNamed("WKScriptMessageHandler")]):
    """接收网页发来的消息（回调在主线程执行）。"""

    def initWithCallback_(self, callback):
        self = objc.super(ScriptHandler, self).init()
        if self is None:
            return None
        self.callback = callback
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            body = message.body()
            payload = dict(body) if body is not None else {}
        except Exception:
            payload = {}
        if self.callback:
            try:
                self.callback(payload)
            except Exception as exc:
                log().warning("处理网页消息失败：%s", exc)


class MainWindow:
    """纯 Python 对象（不作为 AppKit 目标，因此不受 selector 命名约束）。"""

    def __init__(self, url: str, width: int, height: int, title: str, callback):
        self.url = url
        self.width = int(width)
        self.height = int(height)
        self.title = title
        self.callback = callback
        self.window = None
        self.web = None
        self.handler = None

    def build(self):
        if self.window is not None:
            return self.window

        rect = NSMakeRect(0, 0, self.width, self.height)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, STYLE, NSBackingStoreBuffered, False
        )
        win.setTitle_(self.title)
        win.setBackgroundColor_(NSColor.windowBackgroundColor())
        win.setFrameAutosaveName_("DailyWallpaperMainWindow")
        win.setReleasedWhenClosed_(False)
        win.center()

        # 注意：不要给 NSWindow 设图标。PyObjC 的 NSWindow 没有 setIcon_ 方法
        # （窗口标题栏左上角的代理图标是 NSDocument 的机制，不是 NSWindow 的 API），
        # 调用会抛 AttributeError → 窗口创建中断 → 窗口永远打不开（2026-10-25 踩坑）。
        # 标题栏代理图标保持系统默认即可。

        handler = ScriptHandler.alloc().initWithCallback_(self.callback)
        ucc = WKUserContentController.alloc().init()
        ucc.addScriptMessageHandler_name_(handler, "native")
        config = WKWebViewConfiguration.alloc().init()
        config.setUserContentController_(ucc)

        web = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, self.width, self.height), config
        )
        web.setAutoresizingMask_(0x12)  # 随窗口缩放
        win.setContentView_(web)

        self.handler = handler
        self.web = web
        self.window = win
        web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(self.url)))
        return win

    def _windowserver_state(self) -> tuple:
        """查 WindowServer 里属于本进程、且**在屏幕上**的窗口尺寸。

        返回 (width, height)：取面积最大的那个「在屏幕上」的窗口。
        返回 (-1, -1) 表示查不到。

        三个关键点（都是实测踩出来的）：
        1. 用 PID 匹配，不用 windowNumber —— windowNumber 在窗口
           重建/展开过程中会变，对不上就误判。
        2. 必须筛 `kCGWindowIsOnscreen` —— Dock 里的小窗虽然 on=True，
           但它是 Dock 的代理缩略图，不是真实窗口尺寸。
        3. 必须筛掉 height < 100 的高瘦窗口 —— 本进程有 4 个 2560x30
           的菜单栏宿主窗口，宽度 2560，会把「取最大宽度」判据彻底污染
           （曾导致校验恒过，等于没校验）。
        """
        try:
            import Quartz
            from Foundation import NSProcessInfo

            # 注意：NSApplication 没有 processIdentifier 方法（PyObjC 里会报
            # 'NSApplication' object has no attribute 'processIdentifier'），
            # 进程号要走 NSProcessInfo。
            pid = NSProcessInfo.processInfo().processIdentifier()
            wl = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID
            )
            best_w = 0
            best_h = 0
            for w in wl:
                if w.get("kCGWindowOwnerPID") != pid:
                    continue
                if not w.get("kCGWindowIsOnscreen"):
                    continue
                bounds = w.get("kCGWindowBounds") or {}
                width = int(bounds.get("Width") or 0)
                height = int(bounds.get("Height") or 0)
                if height < 100:
                    continue  # 菜单栏 / 状态栏一类的高瘦窗口，跳过
                if width * height > best_w * best_h:
                    best_w, best_h = width, height
            return best_w, best_h
        except Exception as exc:
            log().warning("WindowServer 查询失败（无法判定上屏）：%s", exc)
            return -1, -1  # 异常路径，不据此重试

    def _runloop_wait(self, seconds: float) -> None:
        """在主线程 runloop 上等待若干秒（不阻塞 AppKit 事件处理太久）。

        用于「窗口上屏需要时间落地 + 展开动画」的场景：与其 sleep 死等，
        不如让 runloop 继续转，这样 AppKit 自己的布局/动画能正常推进。
        """
        try:
            from Foundation import NSDate, NSRunLoop, NSDefaultRunLoopMode

            deadline = NSDate.dateWithTimeIntervalSinceNow_(seconds)
            NSRunLoop.currentRunLoop().runMode_beforeDate_(
                NSDefaultRunLoopMode, deadline
            )
        except Exception as exc:
            log().debug("runloop 等待异常：%s", exc)
            import time

            time.sleep(seconds)

    def show(self):
        log().info("show() 入口")
        win = self.build()
        log().info("show() build 完成")

        # 地面真相自愈（2026-10-25 核心修复）：
        #
        # 实测规律（WindowServer 数据，不是猜测）：
        #   · 冷启动后**什么都不做**等 12s → 窗口仍是 90x97 的 Dock 小窗
        #   · 触发一次二次 show()      → 立刻变 1180x812 on=True，且稳定保持 10s+
        #   · 窗口在 Dock 位置（90x97）时，AppKit 的 isVisible() 依然返回 True
        #     → 「visible=True」这个信号完全是假的，不能作为判据
        #   · 冷启动时窗口会经历「Dock 展开动画」：中途宽度是 1160 这类
        #     过渡值，动画结束后又缩回 90x97 → **只查一次宽度会误判成功**
        #
        # 所以策略是：
        #   1. 先 deminiaturize（把窗口从 Dock 里彻底拉出来）+ orderFront
        #   2. 等动画结束（连续两次采样宽度稳定）
        #   3. 宽度达标才认成功，否则重做（最多 3 轮）
        need = int(self.width * 0.5)
        attempt = 0
        while attempt < 3:
            attempt += 1
            NSApp.activateIgnoringOtherApps_(True)

            # 窗口若在 Dock 里，先彻底展开。
            # makeKeyAndOrderFront_ 对已 miniaturize 的窗口是无效的，
            # 必须先 deminiaturize_ 再 order front。
            try:
                if win.isMiniaturized():
                    log().info("窗口在 Dock 中，先 deminiaturize 展开")
                    win.deminiaturize_(None)
            except Exception as exc:
                log().warning("deminiaturize 失败：%s", exc)

            win.makeKeyAndOrderFront_(None)
            win.orderFrontRegardless()

            # 等 Dock 展开动画走完：连续两次采样，尺寸稳定才算落地。
            # （动画中途的尺寸是过渡值，只查一次会误判成成功。）
            self._runloop_wait(0.6)
            w1, h1 = self._windowserver_state()
            self._runloop_wait(0.5)
            w2, h2 = self._windowserver_state()
            stable = (w1 == w2 and h1 == h2)

            log().info(
                "上屏校验（第 %d 轮）：WindowServer %sx%s → %sx%s（稳定=%s）期望宽>=%d",
                attempt, w1, h1, w2, h2, stable, need,
            )
            if w2 < 0:
                # 查询异常，不据此判定失败，避免无意义重试
                break
            if w2 >= need and stable:
                # 上屏后把位置归位到居中。
                # 自愈重试过程中反复 orderFront 可能让窗口停在偏移位置
                # （实测出现过 X=1248），这里统一复位。
                try:
                    win.center()
                except Exception:
                    pass
                break
            log().warning(
                "窗口未真正上屏（第 %d 轮，%sx%s→%sx%s 稳定=%s），重试",
                attempt, w1, h1, w2, h2, stable,
            )
            # 递增等待，给 WindowServer 落地 + 动画更多时间
            self._runloop_wait(0.6 * attempt)

        log().info("show() orderFront 完成")
        # 最终自检：把窗口真实状态写进日志。
        try:
            screens = NSScreen.screens()
            n = screens.count() if screens else 0
            log().info(
                "主窗口状态：visible=%s miniaturized=%s frame=%s screens=%d windowNumber=%s",
                win.isVisible(),
                win.isMiniaturized(),
                win.frame(),
                n,
                win.windowNumber(),
            )
        except Exception as exc:
            log().warning("窗口自检失败：%s", exc)

    def push(self, event: str, data) -> None:
        """把事件推给网页（需在主线程调用）。"""
        if self.web is None:
            return
        js = f"window.__push && window.__push({json.dumps(event)}, {json.dumps(data, ensure_ascii=False)});"
        try:
            self.web.evaluateJavaScript_completionHandler_(js, None)
        except Exception as exc:
            log().debug("推送事件失败：%s", exc)
