"""配置中心：集中读取 config.yaml，解析路径，支持就地回写（保留注释）。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import miniyaml

DEFAULT_FILENAME = "config.yaml"
LOCAL_FILENAME = "config.local.yaml"  # 本地私密覆盖（.gitignore），用于 API Key 等不入库配置

_DEFAULTS: Dict[str, Any] = {
    "app": {
        "change_on_launch": True,
        "show_cached_first": True,
        "schedule_times": ["09:00"],
        "interval_minutes": 0,
        "retry": {"max_attempts": 3, "base_delay_seconds": 5, "max_delay_seconds": 300},
    },
    "display": {
        "fill_mode": "fill",
        "background_color": "#15171a",
        "multi_screen": "independent",
        "recompose": True,
    },
    "content": {
        "min_width": 1920,
        "min_height": 1080,
        "orientation": "landscape",
        "blocked_keywords": [],
        "blocked_keywords_zh": [],
        "topics": ["mountain landscape"],
        "topics_per_fetch": 2,
    },
    "sources": {},
    "storage": {
        "cache_dir": "cache",
        "max_cached_files": 200,
        "favorites_dir": "Favorites",
        "data_dir": "data",
        "save_dir": "~/Pictures/DaoPapers",
    },
    "ui": {"window_width": 1180, "window_height": 780, "language": "zh-CN"},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, root: str, data: Dict[str, Any], path: str):
        self.root = os.path.abspath(root)
        self.path = path
        self.data: Dict[str, Any] = data

    # ---------------- 载入 ---------------- #
    @classmethod
    def load(cls, root: str, filename: str = DEFAULT_FILENAME) -> "Config":
        path = os.path.abspath(os.path.join(root, filename))
        data: Dict[str, Any] = {}
        if os.path.exists(path):
            try:
                data = miniyaml.load(path)
            except Exception:
                data = {}
        # 本地覆盖文件（如 API Key），不存在则跳过；优先级高于 config.yaml
        local_path = os.path.abspath(os.path.join(root, LOCAL_FILENAME))
        if os.path.exists(local_path):
            try:
                data = _deep_merge(data, miniyaml.load(local_path))
            except Exception:
                pass  # 覆盖文件损坏时不阻断主配置加载
        merged = _deep_merge(_DEFAULTS, data)
        return cls(root=root, data=merged, path=path)

    def reload(self) -> None:
        fresh = Config.load(self.root, os.path.basename(self.path))
        self.data = fresh.data

    # ---------------- 读取 ---------------- #
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> Dict[str, Any]:
        value = self.data.get(name)
        return value if isinstance(value, dict) else {}

    def resolve(self, value: Optional[str], default_relative: str = "") -> str:
        """把配置里的路径解析为绝对路径（支持 ~ 与相对路径）。"""
        raw = str(value or default_relative).strip()
        if not raw:
            raw = default_relative
        raw = os.path.expanduser(raw)
        if not os.path.isabs(raw):
            raw = os.path.join(self.root, raw)
        return os.path.abspath(raw)

    # ---------------- 目录 ---------------- #
    @property
    def cache_dir(self) -> str:
        return self.resolve(self.get("storage.cache_dir"), "cache")

    @property
    def favorites_dir(self) -> str:
        return self.resolve(self.get("storage.favorites_dir"), "Favorites")

    @property
    def data_dir(self) -> str:
        return self.resolve(self.get("storage.data_dir"), "data")

    @property
    def log_dir(self) -> str:
        return os.path.join(self.data_dir, "logs")

    @property
    def composed_dir(self) -> str:
        return os.path.join(self.cache_dir, "_composed")

    @property
    def save_dir(self) -> str:
        return self.resolve(self.get("storage.save_dir"), "~/Pictures/DaoPapers")

    # ---------------- 常用取值 ---------------- #
    @property
    def fill_mode(self) -> str:
        mode = str(self.get("display.fill_mode", "fill")).lower()
        return mode if mode in ("fill", "fit", "stretch", "center") else "fill"

    @property
    def multi_screen(self) -> str:
        mode = str(self.get("display.multi_screen", "independent")).lower()
        return mode if mode in ("same", "independent") else "independent"

    @property
    def schedule_times(self) -> List[str]:
        raw = self.get("app.schedule_times") or []
        out: List[str] = []
        for item in raw:
            text = str(item).strip()
            if len(text) == 5 and text[2] == ":" and text.replace(":", "").isdigit():
                out.append(text)
        return out

    @property
    def interval_minutes(self) -> int:
        try:
            return int(self.get("app.interval_minutes", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def enabled_sources(self) -> List[str]:
        order = ["unsplash", "bing", "wallhaven", "picsum", "local"]
        out: List[str] = []
        for name in order:
            sec = self.section("sources").get(name)
            if isinstance(sec, dict) and bool(sec.get("enabled")):
                # 需要 Key 却没填 Key 的源直接跳过
                if name == "unsplash" and not str(sec.get("api_key") or "").strip():
                    continue
                out.append(name)
        return out

    # ---------------- 写入 ---------------- #
    def save_updates(self, updates: Dict[str, Any]) -> None:
        """就地更新配置文件（保留注释），随后重新载入。"""
        miniyaml.save(self.path, updates)
        self.reload()

    def as_plain(self) -> Dict[str, Any]:
        """给界面用的可序列化快照。"""
        return self.data
