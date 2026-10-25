"""AppKit 主线程调度。

NSScreen / NSImage / NSWorkspace 等 AppKit API 有主线程纪律；引擎的换图任务
跑在后台线程（启动任务、菜单 spawn、调度器 tick），不归位会静默失败甚至崩
图形栈（例如 setDesktopImageURL 在后台线程调用时部分 macOS 版本直接无效）。

放在独立模块而不是 runner.py：engine / wallpaper / sources 都会用到，
避免循环 import（runner → engine → wallpaper → runner）。
"""

from __future__ import annotations

import threading

import objc
from AppKit import NSObject


def _log_exception(exc: BaseException) -> None:
    """记录主线程任务里抛出的异常。

    不能直接 import app.logger（会循环 import：logger → ... → mainthread），
    所以延迟到真正需要时再导入。
    """
    try:
        from .logger import get as log

        log().error("主线程任务异常：%s", exc, exc_info=True)
    except Exception:
        import traceback

        traceback.print_exc()


class _MainTask(NSObject):
    def initWithFn_(self, fn):
        self = objc.super(_MainTask, self).init()
        if self is None:
            return None
        self.fn = fn
        return self

    def run_(self, sender):
        # 必须兜住异常：performSelectorOnMainThread 的任务里抛出的异常会被
        # Cocoa 的默认处理器吞掉（日志一个字都不打），调用方会误以为成功了。
        # 2026-10-25 踩坑：窗口创建里一处 API 拼错 → 异常被吞 → 日志照样打
        # 「显示主窗口」，但窗口根本没出现，排查完全失去线索。
        try:
            self.fn()
        except BaseException as exc:  # noqa: BLE001 - 主线程任务必须记录
            _log_exception(exc)


def run_on_main(fn) -> None:
    """异步：把 fn 排到主线程执行，不等待结果。"""
    task = _MainTask.alloc().initWithFn_(fn)
    task.performSelectorOnMainThread_withObject_waitUntilDone_("run:", None, False)


def call_on_main(fn):
    """同步：在主线程执行 fn 并返回其结果；调用线程阻塞到完成为止。

    已在主线程则直接执行（避免死等）。fn 抛出的异常会原样抛回调用方——
    后台线程因此能像本地调用一样 try/except。
    """
    if threading.current_thread() is threading.main_thread():
        return fn()
    box: dict = {}
    done = threading.Event()

    def job():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 原样回传调用方
            box["error"] = exc
        finally:
            done.set()

    run_on_main(job)
    done.wait()
    if "error" in box:
        raise box["error"]
    return box.get("result")
