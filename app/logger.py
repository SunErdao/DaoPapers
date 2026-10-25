"""日志：只写文件，不弹窗、不打扰。"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_NAME = "daily-wallpaper"


def setup(log_dir: str, level: str = "INFO", verbose_console: bool = False) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(_LOG_NAME)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        os.path.join(log_dir, "app.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if verbose_console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    return logger


def get() -> logging.Logger:
    return logging.getLogger(_LOG_NAME)
