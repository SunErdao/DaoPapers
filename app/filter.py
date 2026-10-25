"""内容过滤：把人物肖像类壁纸挡在外面，并按分辨率/构图/题材做筛选。

过滤顺序（命中即丢弃，理由会写进日志）：
  1. 屏蔽表（用户点过「不感兴趣」的图、作者）
  2. 分辨率下限
  3. 构图方向
  4. 人物肖像类关键词（中英文，按词边界匹配标题/描述/标签）
"""

from __future__ import annotations

import random
import re
from typing import Iterable, List, Optional, Sequence

from .models import Photo

# 人物 / 肖像相关的高危词根：即使配置里没写，也一律拦截
_EXTRA_PEOPLE_ROOTS = (
    "portrait",
    "people",
    "person",
    "human",
    "selfie",
    "bikini",
    "swimsuit",
    "lingerie",
    "underwear",
    "nude",
    "naked",
    "sexy",
    "glamour",
    "bodybuilder",
    "cosplay",
    "wedding",
    "bride",
    "bridesmaid",
    "groom",
    "couple",
    "crowd",
)

_ZH_PEOPLE = (
    "人物",
    "人像",
    "肖像",
    "写真",
    "美女",
    "帅哥",
    "泳装",
    "比基尼",
    "内衣",
    "婚纱",
    "新娘",
    "街拍",
    "模特",
    "自拍",
    "裸",
    "人群",
)


def _word_re(word: str) -> str:
    w = re.escape(word.strip().lower())
    return rf"(?<![a-z0-9]){w}(?:s|es)?(?![a-z0-9])"


class ContentFilter:
    def __init__(self, cfg):
        self.cfg = cfg
        content = cfg.section("content")

        self.min_width = int(content.get("min_width") or 1920)
        self.min_height = int(content.get("min_height") or 1080)
        self.orientation = str(content.get("orientation") or "landscape").lower()

        blocked: List[str] = [str(x).lower() for x in (content.get("blocked_keywords") or [])]
        blocked += list(_EXTRA_PEOPLE_ROOTS)
        # 去重并保持顺序
        seen, words = set(), []
        for w in blocked:
            if w and w not in seen:
                seen.add(w)
                words.append(w)
        self._en_pattern = re.compile("|".join(_word_re(w) for w in words), re.IGNORECASE)

        zh: List[str] = [str(x) for x in (content.get("blocked_keywords_zh") or [])]
        zh += list(_ZH_PEOPLE)
        zh = [w for w in dict.fromkeys(zh) if w]
        self._zh_words = zh

        self.topics: List[str] = [str(x) for x in (content.get("topics") or [])]
        self.topics_per_fetch = max(1, int(content.get("topics_per_fetch") or 1))

    # ---------------- 屏蔽表 ---------------- #
    def is_blocked(self, photo: Photo, blocklist: dict) -> bool:
        if photo.key() in (blocklist.get("ids") or []):
            return True
        if photo.url_key() and photo.url_key() in (blocklist.get("urls") or []):
            return True
        author = (photo.author or "").strip().lower()
        if author and author in [a.lower() for a in (blocklist.get("authors") or [])]:
            return True
        return False

    # ---------------- 主入口 ---------------- #
    def reject_reason(self, photo: Photo, blocklist: Optional[dict] = None) -> Optional[str]:
        if not photo.source_url and not photo.fallback_url:
            return "没有可用的图片直链"
        if blocklist and self.is_blocked(photo, blocklist):
            return "已被屏蔽（不感兴趣）"
        if photo.width and photo.width < self.min_width:
            return f"宽度不足（{photo.width}<{self.min_width}）"
        if photo.height and photo.height < self.min_height:
            return f"高度不足（{photo.height}<{self.min_height}）"
        if self.orientation == "landscape" and photo.width and photo.height:
            if photo.width < photo.height:
                return "非横构图"
        if self.orientation == "portrait" and photo.width and photo.height:
            if photo.width > photo.height:
                return "非竖构图"

        text = photo.searchable_text()
        hit = self._en_pattern.search(text)
        if hit:
            return f"命中人物/肖像屏蔽词：{hit.group(0)}"
        for word in self._zh_words:
            if word in text:
                return f"命中人物/肖像屏蔽词：{word}"
        return None

    def allowed(self, photos: Iterable[Photo], blocklist: Optional[dict] = None) -> List[Photo]:
        out: List[Photo] = []
        for p in photos:
            if self.reject_reason(p, blocklist) is None:
                out.append(p)
        return out

    # ---------------- 题材轮换 ---------------- #
    def pick_topic(self) -> str:
        """随机组合若干题材词，作为本轮换新的检索词。"""
        if not self.topics:
            return "landscape wallpaper"
        k = min(self.topics_per_fetch, len(self.topics))
        picked: Sequence[str] = random.sample(self.topics, k)
        return " ".join(picked)
