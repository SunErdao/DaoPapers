"""Picsum 图源：无需 Key 的兜底随机图。

题材不可控（偶有人物），因此默认只在其它图源都失败时使用，并且同样会经过
人物肖像过滤（基于作者名与 URL 指纹的屏蔽表）。
"""

from __future__ import annotations

import random
from typing import List

from .. import http
from ..models import Photo
from .base import Source

WIDTH = 3840
HEIGHT = 2160


class PicsumSource(Source):
    name = "picsum"
    label = "Picsum（兜底）"

    def fetch(self, limit: int = 8, ctx: dict = None) -> List[Photo]:
        page = random.randint(1, 20)
        url = f"https://picsum.photos/v2/list?page={page}&limit=30"
        data = http.get_json(url, timeout=15)
        if not isinstance(data, list):
            return []

        photos: List[Photo] = []
        random.shuffle(data)
        for it in data:
            pid = it.get("id")
            if pid is None:
                continue
            photos.append(
                Photo(
                    id=f"picsum_{pid}",
                    source=self.name,
                    title=f"Picsum · {pid}",
                    author=it.get("author") or "",
                    page_url=it.get("url") or "",
                    source_url=f"https://picsum.photos/id/{pid}/{WIDTH}/{HEIGHT}",
                    fallback_url=f"https://picsum.photos/id/{pid}/1920/1080",
                    width=WIDTH,
                    height=HEIGHT,
                    description="",
                    tags=["picsum"],
                )
            )
            if len(photos) >= max(1, limit):
                break
        return photos
