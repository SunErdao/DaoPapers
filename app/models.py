"""数据模型：统一描述一张壁纸的来源、元信息与本地落盘状态。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Photo:
    """一张候选壁纸（尚未下载）。"""

    id: str
    source: str                 # bing / unsplash / wallhaven / picsum / local
    title: str = "未命名"
    author: str = ""
    author_url: str = ""
    page_url: str = ""          # 图片详情页（来源信息）
    source_url: str = ""        # 图片直链（下载用）
    fallback_url: str = ""      # 直链失效时的备用直链
    width: int = 0
    height: int = 0
    color: str = "#2b2f36"      # 主色，用于加载占位
    description: str = ""
    tags: List[str] = field(default_factory=list)

    def key(self) -> str:
        """全局唯一键：图源 + 图源内 id（用于屏蔽表去重）。"""
        return f"{self.source}:{self.id}"

    def url_key(self) -> str:
        """直链指纹：同一张图换了 id 也能屏蔽。"""
        if not self.source_url:
            return ""
        return hashlib.sha1(self.source_url.encode("utf-8")).hexdigest()[:16]

    def searchable_text(self) -> str:
        parts = [self.title, self.description, " ".join(self.tags), self.author]
        return " \n ".join(p for p in parts if p).lower()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Photo":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


@dataclass
class Entry:
    """已落盘到本地缓存的一张壁纸（在“牌堆”里可被前后翻页）。"""

    photo: Photo
    file: str                   # 本地缓存文件绝对路径
    downloaded_at: float = 0.0
    applied_at: float = 0.0
    favorite: bool = False
    notes: str = ""

    def key(self) -> str:
        return self.photo.key()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "photo": self.photo.to_dict(),
            "file": self.file,
            "downloaded_at": self.downloaded_at,
            "applied_at": self.applied_at,
            "favorite": self.favorite,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["Entry"]:
        try:
            photo = Photo.from_dict(d.get("photo") or {})
            if not photo.id or not d.get("file"):
                return None
            return cls(
                photo=photo,
                file=d["file"],
                downloaded_at=d.get("downloaded_at", 0.0),
                applied_at=d.get("applied_at", 0.0),
                favorite=d.get("favorite", False),
                notes=d.get("notes", ""),
            )
        except Exception:
            return None
