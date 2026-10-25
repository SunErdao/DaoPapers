"""JS 桥接 API：网页通过 window.webkit.messageHandlers.native 调用这些方法。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from typing import Any, Dict, Tuple

from AppKit import NSModalResponseOK, NSSavePanel, NSWorkspace
from Foundation import NSURL

from .. import wallpaper
from ..logger import get as log
from ..sources import LABELS

# 需要在后台线程执行、完成后推送状态的操作
ASYNC_ACTIONS = {
    "next",
    "prev",
    "refresh",
    "block",
    "apply_favorite",
    "remove_favorite",
    "toggle_favorite",
    "show_key",
}

# 允许从界面回写的配置项（其余请直接编辑 config.yaml）
WRITABLE = (
    "app.change_on_launch",
    "app.schedule_times",
    "app.interval_minutes",
    "app.show_cached_first",
    "display.fill_mode",
    "display.background_color",
    "display.multi_screen",
    "display.recompose",
    "content.min_width",
    "content.min_height",
    "content.orientation",
    "content.topics_per_fetch",
    "sources.bing.enabled",
    "sources.bing.market",
    "sources.bing.count",
    "sources.unsplash.enabled",
    "sources.unsplash.api_key",
    "sources.unsplash.mode",
    "sources.unsplash.content_filter",
    "sources.wallhaven.enabled",
    "sources.wallhaven.api_key",
    "sources.wallhaven.categories",
    "sources.wallhaven.purity",
    "sources.wallhaven.sorting",
    "sources.picsum.enabled",
    "sources.local.enabled",
    "sources.local.folder",
    "storage.save_dir",
    "storage.max_cached_files",
)


class Api:
    def __init__(self, app):
        self.app = app

    # ---------------- 分发 ---------------- #
    def handle(self, msg: Dict[str, Any]) -> Tuple[bool, Any]:
        action = str((msg or {}).get("action") or "")
        payload = (msg or {}).get("payload") or {}
        fn = getattr(self, f"do_{action}", None)
        if fn is None:
            return False, f"未知操作：{action}"
        if action in ASYNC_ACTIONS:
            threading.Thread(target=self._run_async, args=(fn, payload), daemon=True).start()
            return True, {"async": True}
        try:
            return True, fn(payload)
        except Exception as exc:  # 界面永远不该崩
            log().warning("操作 %s 失败：%s", action, exc)
            return False, str(exc)

    def _run_async(self, fn, payload):
        try:
            fn(payload)
        except Exception as exc:
            log().warning("异步操作失败：%s", exc)
        finally:
            self.app.push_state()

    # ---------------- 查询 ---------------- #
    def do_get_state(self, payload) -> dict:
        return self.app.engine.state()

    def do_get_config(self, payload) -> dict:
        cfg = self.app.cfg
        return {
            "root": self.app.root,
            "config_path": cfg.path,
            "app": {
                "change_on_launch": bool(cfg.get("app.change_on_launch", True)),
                "show_cached_first": bool(cfg.get("app.show_cached_first", True)),
                "schedule_times": cfg.schedule_times,
                "interval_minutes": cfg.interval_minutes,
            },
            "display": {
                "fill_mode": cfg.fill_mode,
                "background_color": str(cfg.get("display.background_color", "#15171a")),
                "multi_screen": cfg.multi_screen,
                "recompose": bool(cfg.get("display.recompose", True)),
            },
            "content": {
                "min_width": int(cfg.get("content.min_width", 1920)),
                "min_height": int(cfg.get("content.min_height", 1080)),
                "orientation": str(cfg.get("content.orientation", "landscape")),
                "topics_per_fetch": int(cfg.get("content.topics_per_fetch", 2)),
            },
            "sources": cfg.section("sources"),
            "source_labels": LABELS,
            "storage": {
                "save_dir": cfg.save_dir,
                "max_cached_files": int(cfg.get("storage.max_cached_files", 200)),
            },
            "screens": wallpaper.screen_info(),
            "next_fire": self.app.next_fire_hint(),
        }

    # ---------------- 动作 ---------------- #
    def do_next(self, payload):
        self.app.engine.goto(1)

    def do_prev(self, payload):
        self.app.engine.goto(-1)

    def do_refresh(self, payload):
        self.app.engine.refresh(force_new=True)

    def do_toggle_favorite(self, payload):
        self.app.engine.favorite_current()

    def do_block(self, payload):
        self.app.engine.block_current(block_author=bool(payload.get("block_author")))

    def do_apply_favorite(self, payload):
        self.app.engine.apply_favorite(str(payload.get("key") or ""))

    def do_show_key(self, payload):
        """把「最近使用」里的某一张重新设为当前壁纸。"""
        key = str(payload.get("key") or "")
        store = self.app.engine.store
        for i, e in enumerate(store.deck):
            if e.key() == key and os.path.exists(e.file):
                store.index = i
                self.app.engine._apply(e)
                return True
        return False

    def do_remove_favorite(self, payload):
        self.app.engine.store.remove_favorite(str(payload.get("key") or ""))
        self.app.engine.store.save_favorites()

    def do_open_source(self, payload):
        url = str(payload.get("url") or "")
        if not url:
            return False
        self.app.open_url(url)

    def do_reveal(self, payload):
        path = str(payload.get("path") or "")
        if path and os.path.exists(path):
            NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
                [NSURL.fileURLWithPath_(path)]
            )
            return True
        return False

    def do_save(self, payload) -> dict:
        """弹出保存面板，把当前壁纸存到用户指定位置。"""
        entry = self.app.engine.store.current
        if not entry:
            return {"ok": False, "reason": "没有当前壁纸"}
        ext = os.path.splitext(entry.file)[1] or ".jpg"
        safe = "".join(c if c not in '/\\:*?"<>|' else "_" for c in entry.photo.title)[:60]
        panel = NSSavePanel.savePanel()
        panel.setTitle_("保存壁纸")
        panel.setNameFieldStringValue_(f"{safe or entry.photo.id}{ext}")
        panel.setDirectoryURL_(NSURL.fileURLWithPath_(self.app.cfg.save_dir))
        panel.setCanCreateDirectories_(True)
        if panel.runModal() != NSModalResponseOK:
            return {"ok": False, "reason": "已取消"}
        dest = panel.URL().path()
        try:
            shutil.copyfile(entry.file, dest)
            log().info("已保存到：%s", dest)
            return {"ok": True, "path": dest}
        except OSError as exc:
            return {"ok": False, "reason": str(exc)}

    def do_save_config(self, payload) -> dict:
        updates = {k: v for k, v in (payload or {}).items() if k in WRITABLE}
        if not updates:
            return {"ok": False, "reason": "没有可写入的变更"}
        try:
            self.app.cfg.save_updates(updates)
        except Exception as exc:
            log().warning("写入配置失败：%s", exc)
            return {"ok": False, "reason": str(exc)}
        self.app.engine.reload()
        self.app.restart_scheduler()
        # 显示相关配置变更后立即重绘一次
        if any(k.startswith("display.") for k in updates):
            cur = self.app.engine.store.current
            if cur:
                self.app.engine._apply(cur)
        return {"ok": True, "updated": list(updates.keys())}

    def do_open_config_file(self, payload) -> bool:
        self.app.open_config_file()
        return True

    def do_reload_config(self, payload) -> bool:
        self.app.engine.reload()
        self.app.restart_scheduler()
        return True

    def do_clear_blocked(self, payload) -> bool:
        self.app.engine.store.unblock_all()
        return True

    def do_open_settings(self, payload) -> bool:
        return True

    def do_quit(self, payload) -> bool:
        self.app.quit()
        return True

    def do_log_path(self, payload):
        return os.path.join(self.app.cfg.log_dir, "app.log")
