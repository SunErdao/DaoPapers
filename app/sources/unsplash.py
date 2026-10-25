"""Unsplash 图源：题材最可控（按关键词 / 官方话题 / 收藏集检索）。

需要免费的 Access Key：https://unsplash.com/oauth/applications
"""

from __future__ import annotations

import random
from typing import List
from urllib.parse import quote

from .. import http
from ..models import Photo
from .base import Source

API = "https://api.unsplash.com"


def _with_params(raw_url: str, width: int = 3840, quality: int = 85) -> str:
    sep = "&" if "?" in raw_url else "?"
    return f"{raw_url}{sep}w={width}&q={quality}&fm=jpg&fit=max"


class UnsplashSource(Source):
    name = "unsplash"
    label = "Unsplash"

    def fetch(self, limit: int = 8, ctx: dict = None) -> List[Photo]:
        key = str(self.settings.get("api_key") or "").strip()
        if not key:
            return []

        s = self.settings
        mode = str(s.get("mode") or "query").lower()
        try:
            per_page = int(s.get("per_page") or 30)
        except (TypeError, ValueError):
            per_page = 30
        per_page = max(1, min(30, per_page))
        content_filter = str(s.get("content_filter") or "low")
        headers = {"Authorization": f"Client-ID {key}", "Accept-Version": "v1"}

        if mode == "topics":
            ids = [str(x) for x in (s.get("topic_ids") or []) if str(x).strip()]
            if not ids:
                ids = ["wallpapers"]
            url = f"{API}/topics/{random.choice(ids)}/photos?per_page={per_page}&orientation=landscape"
        elif mode == "collection":
            ids = [str(x) for x in (s.get("collection_ids") or []) if str(x).strip()]
            if not ids:
                return []
            url = f"{API}/collections/{random.choice(ids)}/photos?per_page={per_page}&orientation=landscape"
        else:
            topic = ((ctx or {}).get("topic") or "nature landscape").strip()
            url = (
                f"{API}/search/photos?query={quote(topic)}"
                f"&per_page={per_page}&orientation=landscape&content_filter={content_filter}"
            )

        data = http.get_json(url, headers=headers, timeout=20)
        if isinstance(data, dict) and "results" in data:
            items = data.get("results") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []

        photos: List[Photo] = []
        for it in items:
            urls = it.get("urls") or {}
            raw = urls.get("raw") or urls.get("full")
            if not raw:
                continue
            user = it.get("user") or {}
            links = it.get("links") or {}
            user_links = user.get("links") or {}
            tags: List[str] = []
            for t in it.get("tags") or []:
                title = (t or {}).get("title") if isinstance(t, dict) else str(t)
                if title:
                    tags.append(str(title))

            photos.append(
                Photo(
                    id=f"unsplash_{it.get('id')}",
                    source=self.name,
                    title=(it.get("description") or it.get("alt_description") or "Unsplash").strip(),
                    author=user.get("name") or "",
                    author_url=user_links.get("html") or "",
                    page_url=links.get("html") or "",
                    source_url=_with_params(raw),
                    fallback_url=_with_params(raw, width=2560),
                    width=int(it.get("width") or 0),
                    height=int(it.get("height") or 0),
                    color=it.get("color") or "#2b2f36",
                    description=(it.get("alt_description") or ""),
                    tags=tags,
                )
            )
            if len(photos) >= max(1, limit):
                break
        return photos
