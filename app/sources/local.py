"""本地文件夹图源：把自己收藏的图片目录当作图源。"""

from __future__ import annotations

import os
from typing import List

from .. import imaging
from ..models import Photo
from .base import Source

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".bmp")


class LocalSource(Source):
    name = "local"
    label = "本地文件夹"

    def fetch(self, limit: int = 8, ctx: dict = None) -> List[Photo]:
        folder = os.path.expanduser(str(self.settings.get("folder") or "").strip())
        if not folder or not os.path.isdir(folder):
            return []

        files: List[str] = []
        for root, _dirs, names in os.walk(folder):
            for n in names:
                if n.lower().endswith(EXTS) and not n.startswith("."):
                    files.append(os.path.join(root, n))
        if not files:
            return []

        import random

        random.shuffle(files)
        photos: List[Photo] = []
        for path in files[: max(1, limit)]:
            w, h = imaging.image_size(path)
            rel = os.path.relpath(path, folder)
            photos.append(
                Photo(
                    id=f"local_{rel}",
                    source=self.name,
                    title=os.path.splitext(os.path.basename(path))[0],
                    author="本地文件",
                    page_url="file://" + path,
                    source_url="file://" + path,
                    width=w,
                    height=h,
                    tags=["local"],
                )
            )
        return photos
