"""下载与缓存：带重试、直链兜底、本地文件直取。失败只抛异常，绝不弹窗。"""

from __future__ import annotations

import os
import re
import shutil
import time
from urllib.parse import unquote, urlparse

from . import http
from .models import Photo

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def cache_path(cache_dir: str, photo: Photo) -> str:
    """图片在缓存目录中的落盘路径。"""
    stem = _SAFE.sub("_", photo.id)[:80] or "image"
    ext = os.path.splitext(urlparse(photo.source_url or "").path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".bmp"):
        ext = ".jpg"
    return os.path.join(cache_dir, f"{stem}{ext}")


def _local_path(url: str) -> str:
    if url.startswith("file://"):
        return unquote(urlparse(url).path)
    return url if os.path.isabs(url) and os.path.exists(url) else ""


def ensure(photo: Photo, cache_dir: str, retry: dict = None, log=None) -> str:
    """确保图片已在本地缓存中，返回本地路径；失败抛出 HttpError。"""
    dest = cache_path(cache_dir, photo)
    os.makedirs(cache_dir, exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 20 * 1024:
        return dest

    retry = retry or {}
    attempts = max(1, int(retry.get("max_attempts", 3)))
    base_delay = float(retry.get("base_delay_seconds", 5))
    max_delay = float(retry.get("max_delay_seconds", 300))

    urls = [u for u in (photo.source_url, photo.fallback_url) if u]
    if not urls:
        raise http.HttpError("没有可用的图片直链")

    last: Exception = http.HttpError("未知下载失败")
    for attempt in range(attempts):
        for url in urls:
            local = _local_path(url)
            try:
                if local and os.path.exists(local):
                    shutil.copyfile(local, dest + ".part")
                    os.replace(dest + ".part", dest)
                    return dest
                http.download_to(url, dest, referer=photo.page_url or None, timeout=60)
                if log:
                    log.info("已下载：%s", url)
                return dest
            except Exception as exc:  # noqa: BLE001 - 任何异常都转为重试
                last = exc
                if log:
                    log.warning("下载失败(%d/%d) %s -> %s", attempt + 1, attempts, url, exc)
        if attempt < attempts - 1:
            time.sleep(min(max_delay, base_delay * (2 ** attempt)))
    raise last
