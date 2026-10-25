"""图源基类：所有图源统一返回 Photo 列表，由引擎做过滤与下载。"""

from __future__ import annotations

from typing import Dict, List

from ..models import Photo


class Source:
    name = "base"
    label = "未命名图源"

    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def settings(self) -> Dict:
        sec = self.cfg.section("sources").get(self.name)
        return sec if isinstance(sec, dict) else {}

    def fetch(self, limit: int = 8, ctx: dict = None) -> List[Photo]:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Source {self.name}>"
