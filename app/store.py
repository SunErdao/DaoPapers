"""本地存储：缓存索引（牌堆）、收藏、屏蔽表、运行状态。

全部为 JSON 文本文件，便于查看与手工修改；写入采用「先写 .new 再改名」的原子方式。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from . import atomic
from .models import Entry, Photo

DECK_FILE = "deck.json"
STATE_FILE = "state.json"
BLOCK_FILE = "blocked.json"
FAV_FILE = "favorites.json"


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path: str, payload: Any) -> None:
    atomic.write_json(path, payload)


class Store:
    def __init__(self, data_dir: str, cache_dir: str, favorites_dir: str, max_cached: int = 200):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.favorites_dir = favorites_dir
        self.max_cached = max_cached
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(favorites_dir, exist_ok=True)

        self.deck: List[Entry] = [
            e for e in (Entry.from_dict(d) for d in _read_json(self._p(DECK_FILE), [])) if e
        ]
        self.state: Dict[str, Any] = _read_json(
            self._p(STATE_FILE), {"index": -1, "last_change": "", "applied": {}}
        )
        self.blocked: Dict[str, List[str]] = _read_json(
            self._p(BLOCK_FILE), {"ids": [], "urls": [], "authors": []}
        )
        self.favorites: List[Dict[str, Any]] = _read_json(self._p(FAV_FILE), [])
        self._prune_deck()

    def _p(self, name: str) -> str:
        return os.path.join(self.data_dir, name)

    # ---------------- 牌堆 ---------------- #
    def _prune_deck(self) -> None:
        """丢掉文件已不存在的条目，并按上限裁剪（保留收藏过的）。"""
        alive: List[Entry] = []
        for e in self.deck:
            if os.path.exists(e.file):
                alive.append(e)
        if len(alive) > self.max_cached:
            keep_fav = [e for e in alive if e.favorite]
            others = [e for e in alive if not e.favorite]
            ordered = sorted(others, key=lambda x: x.downloaded_at or 0)
            drop = len(alive) - self.max_cached
            alive = keep_fav + ordered[drop:]
            alive.sort(key=lambda x: x.applied_at or x.downloaded_at or 0)
        self.deck = alive
        if self.state.get("index", -1) >= len(self.deck):
            self.state["index"] = len(self.deck) - 1

    def save_deck(self) -> None:
        _write_json(self._p(DECK_FILE), [e.to_dict() for e in self.deck])

    def save_state(self) -> None:
        _write_json(self._p(STATE_FILE), self.state)

    def save_blocked(self) -> None:
        _write_json(self._p(BLOCK_FILE), self.blocked)

    def save_favorites(self) -> None:
        _write_json(self._p(FAV_FILE), self.favorites)

    @property
    def index(self) -> int:
        return int(self.state.get("index", -1))

    @index.setter
    def index(self, value: int) -> None:
        self.state["index"] = value
        self.save_state()

    @property
    def current(self) -> Optional[Entry]:
        if 0 <= self.index < len(self.deck):
            return self.deck[self.index]
        return None

    def append(self, entry: Entry) -> int:
        exists = next((i for i, e in enumerate(self.deck) if e.key() == entry.key()), None)
        if exists is not None:
            self.deck[exists] = entry
            self.save_deck()
            return exists
        self.deck.append(entry)
        if len(self.deck) > self.max_cached:
            # 从最旧的未收藏条目开始淘汰
            for i, e in enumerate(self.deck):
                if not e.favorite:
                    self.deck.pop(i)
                    break
        self.save_deck()
        return len(self.deck) - 1

    def remove_from_deck(self, key: str) -> None:
        for i, e in enumerate(list(self.deck)):
            if e.key() == key:
                self.deck.pop(i)
                if self.state.get("index", 0) > i:
                    self.state["index"] -= 1
                elif self.state.get("index", -1) >= len(self.deck):
                    self.state["index"] = len(self.deck) - 1
                break
        self.save_deck()
        self.save_state()

    # ---------------- 屏蔽 ---------------- #
    def block(self, photo: Photo, block_author: bool = False) -> None:
        k = photo.key()
        if k not in self.blocked.setdefault("ids", []):
            self.blocked["ids"].append(k)
        uk = photo.url_key()
        if uk and uk not in self.blocked.setdefault("urls", []):
            self.blocked["urls"].append(uk)
        if block_author and photo.author:
            authors = self.blocked.setdefault("authors", [])
            if photo.author not in authors:
                authors.append(photo.author)
        self.save_blocked()

    def unblock_all(self) -> None:
        self.blocked = {"ids": [], "urls": [], "authors": []}
        self.save_blocked()

    # ---------------- 收藏 ---------------- #
    def add_favorite(self, entry: Entry, dest_path: str) -> Dict[str, Any]:
        import shutil

        os.makedirs(self.favorites_dir, exist_ok=True)
        shutil.copyfile(entry.file, dest_path)
        entry.favorite = True
        record = {
            "key": entry.key(),
            "file": dest_path,
            "photo": entry.photo.to_dict(),
            "added_at": time.time(),
        }
        self.favorites = [f for f in self.favorites if f.get("key") != entry.key()]
        self.favorites.insert(0, record)
        self.save_favorites()
        self.save_deck()
        return record

    def remove_favorite(self, key: str) -> None:
        self.favorites = [f for f in self.favorites if f.get("key") != key]
        self.save_favorites()
        for e in self.deck:
            if e.key() == key:
                e.favorite = False
        self.save_deck()

    def is_favorite(self, key: str) -> bool:
        return any(f.get("key") == key for f in self.favorites)

    # ---------------- 缓存清理 ---------------- #
    def cache_size_bytes(self) -> int:
        total = 0
        for name in os.listdir(self.cache_dir):
            fp = os.path.join(self.cache_dir, name)
            if os.path.isfile(fp):
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total
