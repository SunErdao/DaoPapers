"""Wallhaven 图源：图库极大，可通过 categories 精确关闭 people 分类。

API Key（可选，带 Key 可筛选更严格）：https://wallhaven.cc/settings/account
"""

from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import http
from ..models import Photo
from .base import Source

API = "https://wallhaven.cc/api/v1/search"


class WallhavenSource(Source):
    name = "wallhaven"
    label = "Wallhaven"

    def fetch(self, limit: int = 8, ctx: dict = None) -> List[Photo]:
        s = self.settings
        params = {
            "categories": str(s.get("categories") or "100"),  # 默认只开 general
            "purity": str(s.get("purity") or "100"),          # 默认只开 sfw
            "sorting": str(s.get("sorting") or "random"),
            "order": "desc",
            "page": "1",
        }
        atleast = str(s.get("atleast") or "").strip()
        if atleast:
            params["atleast"] = atleast
        ratios = str(s.get("ratios") or "").strip()
        if ratios:
            params["ratios"] = ratios
        key = str(s.get("api_key") or "").strip()
        if key:
            params["apikey"] = key

        url = API + "?" + "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
        data = http.get_json(url, timeout=20)
        items = (data or {}).get("data") or []

        photos: List[Photo] = []
        for it in items:
            direct = it.get("path") or it.get("url") or ""
            if not direct:
                continue
            resolution = str(it.get("resolution") or "")
            w = h = 0
            if "x" in resolution:
                try:
                    w, h = (int(x) for x in resolution.lower().split("x")[:2])
                except ValueError:
                    w = h = 0
            photos.append(
                Photo(
                    id=f"wallhaven_{it.get('id')}",
                    source=self.name,
                    title=f"Wallhaven · {it.get('id')}",
                    author="",
                    page_url=it.get("url") or "",
                    source_url=direct,
                    width=w,
                    height=h,
                    color=it.get("color") or "#2b2f36",
                    tags=[str(t) for t in (it.get("tags") or []) if isinstance(t, str)],
                )
            )
            if len(photos) >= max(1, limit):
                break
        return photos
