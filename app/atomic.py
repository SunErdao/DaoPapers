"""原子写入：先写 .new 再改名；受限环境（禁止改名）自动降级为直接覆盖。"""

from __future__ import annotations

import json
import os
import shutil


def replace(src: str, dst: str) -> None:
    try:
        os.replace(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    replace(tmp, path)


def write_json(path: str, payload) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
