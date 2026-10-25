"""Bing 每日壁纸：无需 API Key，题材以自然风光 / 城市地标为主，人物极少。"""

from __future__ import annotations

import hashlib
import re
from typing import List

from .. import http
from ..logger import get as log
from ..models import Photo
from .base import Source

_SIZE_RE = re.compile(r"_(\d+)x(\d+)\.(jpg|jpeg|png)", re.IGNORECASE)
_UHD = "_3840x2160.jpg"


def _parse_copyright(text: str):
    """Bing 的 copyright 形如「湖光山色 (© 张三/Getty)」。"""
    raw = (text or "").strip()
    m = re.match(r"^(.*?)\s*[（(]\s*(.*?)\s*[)）]\s*$", raw)
    if m:
        title = m.group(1).strip()
        author = m.group(2).replace("©", "").strip()
        return (title or raw), author
    return raw.replace("©", "").strip(), ""


class BingSource(Source):
    name = "bing"
    label = "Bing 每日壁纸"

    def _markets(self) -> List[str]:
        raw = self.settings.get("market") or "zh-CN"
        if isinstance(raw, (list, tuple)):
            vals = [str(x).strip() for x in raw]
        else:
            vals = [x.strip() for x in str(raw).split(",")]
        out = [v for v in vals if v]
        return out or ["zh-CN"]

    def fetch(self, limit: int = 8, ctx: dict = None) -> List[Photo]:
        s = self.settings
        markets = self._markets()
        try:
            n = int(s.get("count") or 8)
        except (TypeError, ValueError):
            n = 8
        n = max(1, min(16, n))
        prefer_uhd = bool(s.get("prefer_uhd", True))

        # 各市场当天的图不同，逐个市场抓，按 id 去重后合并
        photos: List[Photo] = []
        seen = set()
        for market in markets:
            if len(photos) >= max(1, limit):
                break
            url = (
                "https://www.bing.com/HPImageArchive.aspx"
                f"?format=js&idx=0&n={n}&mkt={market}"
            )
            try:
                data = http.get_json(url, timeout=15)
            except Exception as exc:
                log().warning("Bing 市场 %s 抓取失败：%s", market, exc)
                continue
            for it in (data or {}).get("images") or []:
                if len(photos) >= max(1, limit):
                    break
                photo = self._to_photo(it, market, prefer_uhd)
                if photo is None or photo.id in seen:
                    continue
                seen.add(photo.id)
                photos.append(photo)
        return photos

    def _to_photo(self, it: dict, market: str, prefer_uhd: bool):
        rel = it.get("url") or ""
        if not rel:
            return None
        if not rel.startswith("/"):
            rel = "/" + rel
        base_url = "https://www.bing.com" + rel

        # Bing 的高清图只能用 urlbase + "_UHD.jpg" 拼，直接改尺寸参数会 404
        urlbase = (it.get("urlbase") or "").strip()
        source_url, fallback = base_url, ""
        if prefer_uhd and urlbase.startswith("/th?id="):
            uhd_url = "https://www.bing.com" + urlbase + "_UHD.jpg"
            if uhd_url != base_url:
                source_url, fallback = uhd_url, base_url

        title, author = _parse_copyright(it.get("copyright") or "")

        # UHD 链接里没有尺寸信息，真实尺寸在下载后由引擎回写
        m = _SIZE_RE.search(source_url)
        w = int(m.group(1)) if m else 0
        h = int(m.group(2)) if m else 0

        pid = it.get("hsh") or hashlib.sha1(source_url.encode()).hexdigest()[:12]
        return Photo(
            id=f"bing_{it.get('startdate', '')}_{pid}",
            source=self.name,
            title=title or "Bing 每日一图",
            author=author,
            page_url=it.get("copyrightlink") or "https://www.bing.com/",
            source_url=source_url,
            fallback_url=fallback,
            width=w,
            height=h,
            description=it.get("copyright") or "",
            tags=["bing", market],
        )
