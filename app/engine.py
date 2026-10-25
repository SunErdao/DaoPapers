"""引擎：串起「取图 → 过滤 → 缓存 → 设置壁纸 → 记录」这条主链路。

所有网络操作都可能失败；失败时一律静默降级到本地缓存，不弹窗、不打断用户。
"""

from __future__ import annotations

import os
import random
import shutil
import time
from typing import Callable, Dict, List, Optional

from . import downloader, imaging, wallpaper
from .config import Config
from .filter import ContentFilter
from .logger import get as log
from .models import Entry, Photo
from .sources import LABELS, available, build
from .store import Store

SOURCE_LABELS = LABELS


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = Store(
            data_dir=cfg.data_dir,
            cache_dir=cfg.cache_dir,
            favorites_dir=cfg.favorites_dir,
            max_cached=int(cfg.get("storage.max_cached_files", 200) or 200),
        )
        self.content = ContentFilter(cfg)
        self._listeners: List[Callable[[str, dict], None]] = []
        self.last_error: Optional[str] = None
        self._busy = False

    # ---------------- 事件 ---------------- #
    def add_listener(self, fn: Callable[[str, dict], None]) -> None:
        self._listeners.append(fn)

    def _emit(self, event: str, data: dict = None) -> None:
        for fn in list(self._listeners):
            try:
                fn(event, data or {})
            except Exception as exc:  # 监听器异常不影响主流程
                log().warning("事件回调异常：%s", exc)

    # ---------------- 配置 ---------------- #
    def reload(self) -> None:
        self.cfg.reload()
        self.content = ContentFilter(self.cfg)
        self.store.max_cached = int(self.cfg.get("storage.max_cached_files", 200) or 200)
        log().info("配置已重新载入")

    # ---------------- 取图 ---------------- #
    def _candidates(self, want: int = 6) -> List[Photo]:
        names = available(self.cfg)
        if not names:
            self.last_error = "没有启用的图源，请在设置里至少开启一个"
            log().warning(self.last_error)
            return []

        fallback_names = [n for n in names if n != "picsum"]
        picsum_only = bool(
            (self.cfg.section("sources").get("picsum") or {}).get("only_when_others_fail", True)
        )

        ctx = {"topic": self.content.pick_topic()}
        out: List[Photo] = []
        seen = set()
        # 只避开最近看过的 24 张：Bing 每天仅 8 张，全量去重会让「没图可用」被迫降级
        deck_keys = {e.key() for e in self.store.deck[-24:]}

        def collect(group, relax: bool = False) -> None:
            for name in group:
                if len(out) >= want:
                    return
                try:
                    src = build(name, self.cfg)
                    raw = src.fetch(limit=max(10, want * 3), ctx=ctx)
                except Exception as exc:
                    log().warning("图源 %s 取图失败：%s", name, exc)
                    continue
                passed = self.content.allowed(raw, self.store.blocked)
                log().info("图源 %s：取到 %d 张，过滤后 %d 张", name, len(raw), len(passed))
                for p in passed:
                    k = p.key()
                    if k in seen:
                        continue
                    if not relax and k in deck_keys:
                        continue
                    seen.add(k)
                    out.append(p)

        collect(fallback_names)
        if not out and fallback_names:
            # 小图源（Bing 每日仅 8 张）全看过时宁可循环旧图，也不要掉到随机兜底图
            log().info("候选都已看过，改在旧图里循环（不用随机兜底图）")
            collect(fallback_names, relax=True)
        if not out and picsum_only and "picsum" in names:
            collect(["picsum"])
        return out

    def _new_entry(self, photo: Photo) -> Optional[Entry]:
        path = downloader.ensure(
            photo, self.cfg.cache_dir, self.cfg.section("app").get("retry") or {}, log()
        )
        if not photo.width or not photo.height:
            # 图源没给尺寸（例如 Bing UHD）时，按下载后的真实文件回写
            w, h = imaging.image_size(path)
            photo.width, photo.height = w, h
        return Entry(photo=photo, file=path, downloaded_at=time.time())

    # ---------------- 应用 ---------------- #
    def _files_for_screens(self, entry: Entry) -> List[str]:
        info = wallpaper.screen_info()
        n = max(1, len(info))
        if self.cfg.multi_screen == "same" or n == 1:
            return [entry.file]

        files = [entry.file]
        deck = self.store.deck
        idx = self.store.index if self.store.index >= 0 else 0
        for step in range(1, n):
            if not deck:
                break
            cand = deck[(idx + step) % len(deck)]
            if cand.file != entry.file and os.path.exists(cand.file) and cand.file not in files:
                files.append(cand.file)
        while len(files) < n:
            files.append(entry.file)
        return files[:n]

    def _apply(self, entry: Entry) -> bool:
        files = self._files_for_screens(entry)
        results = wallpaper.apply(
            src_paths=files,
            fill_mode=self.cfg.fill_mode,
            background_color=str(self.cfg.get("display.background_color", "#15171a")),
            multi_screen=self.cfg.multi_screen,
            recompose=bool(self.cfg.get("display.recompose", True)),
            composed_dir=self.cfg.composed_dir,
        )
        ok = all(r.get("ok") for r in results) if results else False
        entry.applied_at = time.time()
        self.store.state["last_change"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.store.state["applied"] = entry.photo.to_dict()
        self.store.save_state()
        self.store.save_deck()
        log().info(
            "已应用壁纸：%s（%d 块屏幕，%s）",
            entry.photo.title,
            len(results),
            "成功" if ok else "部分失败",
        )
        return ok

    # ---------------- 对外动作 ---------------- #
    def refresh(self, force_new: bool = True) -> Optional[Entry]:
        """换一张新壁纸。force_new=False 时优先用牌堆里还没看过的缓存。"""
        with_lock = getattr(self, "_busy", False)
        if with_lock:
            return self.store.current
        self._busy = True
        try:
            if not force_new:
                nxt = self._next_unseen()
                if nxt is not None:
                    self._apply(nxt)
                    self._emit("changed", {"entry": self._view(nxt)})
                    return nxt

            photos = self._candidates(want=4)
            random.shuffle(photos)
            for photo in photos:
                try:
                    entry = self._new_entry(photo)
                except Exception as exc:
                    self.last_error = f"下载失败：{exc}"
                    log().warning("下载失败，尝试下一张：%s", exc)
                    continue
                if not entry:
                    continue
                pos = self.store.append(entry)
                self.store.index = pos
                self._apply(entry)
                self.last_error = None
                self._emit("changed", {"entry": self._view(entry)})
                return entry

            # 全部图源都失败 → 用缓存兜底
            self.last_error = "网络不可用，已使用本地缓存"
            log().warning(self.last_error)
            fallback = self._fallback_entry()
            if fallback is not None:
                self._apply(fallback)
                self._emit("changed", {"entry": self._view(fallback)})
            return fallback
        finally:
            self._busy = False

    def _next_unseen(self) -> Optional[Entry]:
        deck = self.store.deck
        if not deck:
            return None
        idx = self.store.index
        if idx + 1 < len(deck):
            entry = deck[idx + 1]
            if os.path.exists(entry.file):
                self.store.index = idx + 1
                return entry
        return None

    def _fallback_entry(self) -> Optional[Entry]:
        """断网兜底：随便挑一张本地已缓存且未被屏蔽的图。"""
        deck = [e for e in self.store.deck if os.path.exists(e.file)]
        blocked_ids = set(self.store.blocked.get("ids") or [])
        deck = [e for e in deck if e.key() not in blocked_ids]
        if not deck:
            return None
        entry = random.choice(deck)
        self.store.index = self.store.deck.index(entry)
        return entry

    def goto(self, delta: int) -> Optional[Entry]:
        """上一张(delta=-1) / 下一张(delta=1)。"""
        deck = self.store.deck
        if not deck:
            return self.refresh(force_new=True)
        idx = self.store.index
        target = idx + delta
        if 0 <= target < len(deck):
            entry = deck[target]
            if not os.path.exists(entry.file):
                return self.refresh(force_new=True)
            self.store.index = target
            self._apply(entry)
            self._emit("changed", {"entry": self._view(entry)})
            return entry
        if delta > 0:
            return self.refresh(force_new=True)
        return None  # 已经在第一张

    def show(self, entry: Entry) -> Optional[Entry]:
        """把某条（收藏/历史）设为当前壁纸。"""
        if not entry or not os.path.exists(entry.file):
            return None
        pos = self.store.append(entry)
        self.store.index = pos
        self._apply(entry)
        self._emit("changed", {"entry": self._view(entry)})
        return entry

    def favorite_current(self, on: Optional[bool] = None) -> bool:
        entry = self.store.current
        if not entry:
            return False
        key = entry.key()
        is_fav = self.store.is_favorite(key)
        target = (not is_fav) if on is None else bool(on)
        if target == is_fav:
            return is_fav
        if target:
            dest = os.path.join(self.favorite_name(entry))
            self.store.add_favorite(entry, dest)
            log().info("已收藏：%s", entry.photo.title)
        else:
            self.store.remove_favorite(key)
            log().info("已取消收藏：%s", entry.photo.title)
        self._emit("changed", {"entry": self._view(entry)})
        return target

    def favorite_name(self, entry: Entry) -> str:
        safe = "".join(c if c not in '/\\:*?"<>|' else "_" for c in entry.photo.title)[:60]
        ext = os.path.splitext(entry.file)[1] or ".jpg"
        base = f"{safe or entry.photo.id}{ext}"
        dest = os.path.join(self.cfg.favorites_dir, base)
        n = 1
        while os.path.exists(dest):
            dest = os.path.join(self.cfg.favorites_dir, f"{safe or entry.photo.id}_{n}{ext}")
            n += 1
        return dest

    def block_current(self, block_author: bool = False) -> Optional[Entry]:
        entry = self.store.current
        if not entry:
            return None
        self.store.block(entry.photo, block_author=block_author)
        self.store.remove_from_deck(entry.key())
        log().info("已屏蔽：%s（同时屏蔽作者=%s）", entry.photo.title, block_author)
        nxt = self.goto(1)
        if nxt is None:
            nxt = self.refresh(force_new=True)
        return nxt

    def save_current_to(self, dest_dir: str) -> Optional[str]:
        entry = self.store.current
        if not entry:
            return None
        os.makedirs(dest_dir, exist_ok=True)
        ext = os.path.splitext(entry.file)[1] or ".jpg"
        safe = "".join(c if c not in '/\\:*?"<>|' else "_" for c in entry.photo.title)[:60]
        dest = os.path.join(dest_dir, f"{safe or entry.photo.id}{ext}")
        n = 1
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, f"{safe or entry.photo.id}_{n}{ext}")
            n += 1
        shutil.copyfile(entry.file, dest)
        log().info("已保存到：%s", dest)
        return dest

    def apply_favorite(self, key: str) -> Optional[Entry]:
        rec = next((f for f in self.store.favorites if f.get("key") == key), None)
        if not rec:
            return None
        photo = Photo.from_dict(rec.get("photo") or {})
        entry = Entry(photo=photo, file=rec["file"], favorite=True, downloaded_at=time.time())
        return self.show(entry)

    # ---------------- 启动 ---------------- #
    def _changed_today(self) -> bool:
        stamp = str(self.store.state.get("last_change") or "")
        return stamp[:10] == time.strftime("%Y-%m-%d")

    def startup(self) -> None:
        """开机/启动时的行为：先用缓存秒开；当天已换过就不再打断当前桌面。"""
        change = bool(self.cfg.get("app.change_on_launch", True))
        cached_first = bool(self.cfg.get("app.show_cached_first", True))

        if self.store.deck and cached_first:
            entry = self.store.current or self.store.deck[-1]
            if entry and os.path.exists(entry.file):
                self.store.index = self.store.deck.index(entry)
                self._apply(entry)
                self._emit("changed", {"entry": self._view(entry)})

        if not change:
            return
        if self._changed_today():
            log().info("今天已更换过壁纸，启动时保持当前桌面")
            return
        self.refresh(force_new=True)

    # ---------------- 视图 ---------------- #
    def _view(self, entry: Optional[Entry]) -> Optional[dict]:
        if not entry:
            return None
        p = entry.photo
        return {
            "key": entry.key(),
            "file": entry.file,
            "title": p.title,
            "author": p.author,
            "author_url": p.author_url,
            "page_url": p.page_url,
            "source": p.source,
            "source_label": SOURCE_LABELS.get(p.source, p.source),
            "description": p.description,
            "tags": p.tags,
            "color": p.color,
            "width": p.width,
            "height": p.height,
            "favorite": self.store.is_favorite(entry.key()),
            "applied_at": entry.applied_at,
        }

    def state(self) -> dict:
        cur = self.store.current
        deck_views = [self._view(e) for e in self.store.deck[-24:]]
        return {
            "root": self.cfg.root,
            "current": self._view(cur),
            "index": self.store.index,
            "total": len(self.store.deck),
            "can_prev": self.store.index > 0,
            "can_next": True,
            "deck": [v for v in deck_views if v],
            "favorites": [
                {
                    "key": f.get("key"),
                    "file": f.get("file"),
                    "title": (f.get("photo") or {}).get("title", ""),
                    "source": (f.get("photo") or {}).get("source", ""),
                    "source_label": SOURCE_LABELS.get(
                        (f.get("photo") or {}).get("source", ""),
                        (f.get("photo") or {}).get("source", ""),
                    ),
                    "added_at": f.get("added_at", 0),
                }
                for f in self.store.favorites
            ],
            "screens": wallpaper.screen_info(),
            "blocked": {
                "ids": len(self.store.blocked.get("ids") or []),
                "authors": len(self.store.blocked.get("authors") or []),
            },
            "status": {
                "last_change": self.store.state.get("last_change", ""),
                "last_error": self.last_error,
                "cache_bytes": self.store.cache_size_bytes(),
                "cached": len(self.store.deck),
                "sources": available(self.cfg),
                "source_labels": SOURCE_LABELS,
            },
        }
