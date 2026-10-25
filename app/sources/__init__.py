"""图源注册表：新增图源只需在此登记。"""

from .base import Source
from .bing import BingSource
from .local import LocalSource
from .picsum import PicsumSource
from .unsplash import UnsplashSource
from .wallhaven import WallhavenSource

REGISTRY = {
    "bing": BingSource,
    "unsplash": UnsplashSource,
    "wallhaven": WallhavenSource,
    "picsum": PicsumSource,
    "local": LocalSource,
}

LABELS = {name: cls.label for name, cls in REGISTRY.items()}

# 按优先级排序：优先题材可控的图源
PRIORITY = ["unsplash", "bing", "wallhaven", "local", "picsum"]


def build(name: str, cfg) -> Source:
    cls = REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"未知图源：{name}")
    return cls(cfg)


def available(cfg) -> list:
    """按配置返回已启用且可用的图源名（按优先级排序）。"""
    enabled = set(cfg.enabled_sources)
    return [n for n in PRIORITY if n in enabled]
