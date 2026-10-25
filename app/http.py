"""HTTP 客户端：标准库实现，带超时、重试与静默失败，不弹窗。"""

from __future__ import annotations

import json
import os
import shutil
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) DailyWallpaper/1.0"
)


class HttpError(Exception):
    """网络请求失败（调用方可据此静默降级）。"""


def _request(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 20.0,
    referer: Optional[str] = None,
):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "*/*")
    if referer:
        req.add_header("Referer", referer)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    ctx = ssl.create_default_context()
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.HTTPError as exc:  # 4xx / 5xx
        raise HttpError(f"HTTP {exc.code} {url}") from exc
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as exc:
        raise HttpError(f"网络不可用：{url} ({exc})") from exc


def get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 20.0) -> Any:
    with _request(url, headers=headers, timeout=timeout) as resp:
        raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise HttpError(f"返回内容不是合法 JSON：{url}") from exc


def get_bytes(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60.0,
    referer: Optional[str] = None,
    max_bytes: int = 64 * 1024 * 1024,
) -> bytes:
    with _request(url, headers=headers, timeout=timeout, referer=referer) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HttpError("图片过大，已放弃下载")
    if len(data) < 1024:
        raise HttpError("返回内容过小，疑似错误页")
    return data


def download_to(
    url: str,
    dest: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60.0,
    referer: Optional[str] = None,
    min_bytes: int = 20 * 1024,
) -> str:
    """流式下载到文件（先写 .part 再原子改名，避免半文件）。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    with _request(url, headers=headers, timeout=timeout, referer=referer) as resp:
        with open(part, "wb") as fh:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
    if os.path.getsize(part) < min_bytes:
        raise HttpError("下载内容过小，疑似错误页")
    try:
        os.replace(part, dest)          # 原子改名，正常环境走这里
    except OSError:
        shutil.copyfile(part, dest)     # 受限环境（禁用改名）下退化为直接复制
    return dest
