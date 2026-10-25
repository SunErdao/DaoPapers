"""壁纸设置：macOS 多显示器，逐屏按实际像素设置，支持不同填充模式。"""

from __future__ import annotations

import hashlib
import os
from typing import List

from AppKit import NSColor, NSImageScaleNone, NSNumber, NSScreen, NSWorkspace
from Foundation import NSURL

from . import imaging
from .logger import get as log
from .mainthread import call_on_main

_SCALING_KEY = "NSWorkspaceDesktopImageScalingKey"
_FILL_COLOR_KEY = "NSWorkspaceDesktopImageFillColorKey"
_CLIPPING_KEY = "NSWorkspaceDesktopImageAllowClippingKey"


def _enumerate() -> List[dict]:
    """内部使用：包含真实的 NSScreen 对象。"""
    out: List[dict] = []
    for i, screen in enumerate(NSScreen.screens()):
        frame = screen.frame()
        scale = float(screen.backingScaleFactor() or 1.0)
        out.append(
            {
                "index": i,
                "screen": screen,
                "scale": scale,
                "points": (int(frame.size.width), int(frame.size.height)),
                "width": int(round(frame.size.width * scale)),
                "height": int(round(frame.size.height * scale)),
                "main": bool(screen == NSScreen.mainScreen()),
            }
        )
    return out


def screen_info() -> List[dict]:
    """给界面用的可序列化显示器信息。"""
    return call_on_main(_enumerate_info)


def _enumerate_info() -> List[dict]:
    """_enumerate 的可序列化形态（必须在主线程调用）。"""
    return [
        {
            "index": s["index"],
            "points": list(s["points"]),
            "scale": s["scale"],
            "width": s["width"],
            "height": s["height"],
            "main": s["main"],
        }
        for s in _enumerate()
    ]


def _composed_path(composed_dir: str, src_path: str, screen: dict, mode: str, bg: str) -> str:
    digest = hashlib.sha1(
        f"{os.path.basename(src_path)}|{screen['width']}x{screen['height']}|{mode}|{bg}".encode()
    ).hexdigest()[:16]
    stem = os.path.splitext(os.path.basename(src_path))[0][:40]
    return os.path.join(composed_dir, f"{stem}_s{screen['index']}_{digest}.jpg")


def apply(
    src_paths: List[str],
    fill_mode: str = "fill",
    background_color: str = "#15171a",
    multi_screen: str = "independent",
    recompose: bool = True,
    composed_dir: str = "",
) -> List[dict]:
    """把图片设置到所有屏幕。

    :param src_paths: 图片路径列表；independent 模式下按屏幕顺序取用（图片不足则循环）
    :return: 每个屏幕的设置结果列表
    """
    if not src_paths:
        return []

    # 整个 AppKit 主体（NSScreen 枚举 / NSImage 合成 / NSWorkspace 设置）
    # 派发主线程执行：调用方（引擎启动任务、菜单 spawn、调度器）都在后台线程。
    return call_on_main(lambda: _apply_all(
        src_paths, fill_mode, background_color, multi_screen, recompose, composed_dir
    ))


def _apply_all(
    src_paths: List[str],
    fill_mode: str,
    background_color: str,
    multi_screen: str,
    recompose: bool,
    composed_dir: str,
) -> List[dict]:
    info = _enumerate()
    if not info:
        log().warning("没有检测到显示器，跳过设置壁纸")
        return []

    ws = NSWorkspace.sharedWorkspace()
    composed_dir = composed_dir or os.path.join(os.path.dirname(src_paths[0]), "_composed")
    os.makedirs(composed_dir, exist_ok=True)

    results: List[dict] = []
    for screen in info:
        if multi_screen == "same":
            src = src_paths[0]
        else:
            src = src_paths[screen["index"] % len(src_paths)]

        target = src
        if recompose:
            target = _composed_path(composed_dir, src, screen, fill_mode, background_color)
            cached_ok = os.path.exists(target) and os.path.getsize(target) > 20 * 1024
            if not cached_ok:
                if not imaging.compose(
                    src, target, screen["width"], screen["height"], fill_mode, background_color
                ):
                    log().warning("合成失败，退回原图：%s", src)
                    target = src

        opts = {
            _SCALING_KEY: NSNumber.numberWithInt_(NSImageScaleNone),
            _FILL_COLOR_KEY: NSColor.blackColor(),
            _CLIPPING_KEY: NSNumber.numberWithBool_(True),
        }
        url = NSURL.fileURLWithPath_(target)
        ok, err = False, None
        try:
            ok, err = ws.setDesktopImageURL_forScreen_options_error_(
                url, screen["screen"], opts, None
            )
        except Exception as exc:  # 防御性：任何异常都不应该崩溃常驻进程
            ok, err = False, exc
        if not ok:
            log().error("设置壁纸失败（屏幕 %d）：%s", screen["index"], err)

        results.append(
            {
                "index": screen["index"],
                "screen": f"{screen['width']}x{screen['height']}",
                "src": src,
                "applied": target,
                "ok": bool(ok),
            }
        )
    return results
