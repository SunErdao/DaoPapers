"""极简 YAML 读写器（仅支持本配置文件用到的语法子集，零依赖）。

支持的语法：
  - 缩进嵌套（空格缩进，2 或 4 空格均可，禁止 Tab）
  - `key: value`  /  `key:`（空值表示嵌套块或 None）
  - 列表：`- item`、`[a, b]`、`[]`
  - 注释：整行 `#` 或行尾 `#`（引号内的 # 会保留，例如 "#15171a"）
  - 标量：字符串 / 整数 / 浮点 / true|false / null

不追求完整 YAML 规范，但对本项目的 config.yaml 足够，且写入时保留注释。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple

__all__ = ["load", "loads", "set_value", "format_scalar"]


# --------------------------------------------------------------------------- #
# 读取
# --------------------------------------------------------------------------- #
def _strip_comment(line: str) -> str:
    out: List[str] = []
    quote = ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _tokenize(text: str) -> List[Tuple[int, str]]:
    rows: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if "\t" in line[: len(line) - len(line.lstrip(" \t"))]:
            raise ValueError("配置文件使用了 Tab 缩进，请改为空格缩进")
        indent = len(line) - len(line.lstrip(" "))
        rows.append((indent, line.strip()))
    return rows


def _scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] == "[" and s[-1] == "]":
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in _split_inline(inner)]
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _split_inline(inner: str) -> List[str]:
    parts, buf, quote = [], [], ""
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _parse_node(rows: List[Tuple[int, str]], i: int, indent: int) -> Tuple[Any, int]:
    if i >= len(rows):
        return None, i
    if rows[i][1].startswith("- ") or rows[i][1] == "-":
        return _parse_list(rows, i, indent)
    return _parse_dict(rows, i, indent)


def _parse_dict(rows: List[Tuple[int, str]], i: int, indent: int) -> Tuple[Dict[str, Any], int]:
    out: Dict[str, Any] = {}
    while i < len(rows):
        ind, txt = rows[i]
        if ind < indent:
            break
        if ind > indent:  # 缩进异常，跳过该行
            i += 1
            continue
        if txt.startswith("- ") or txt == "-":
            break
        key, sep, rest = txt.partition(":")
        if not sep:
            i += 1
            continue
        key = key.strip().strip("\"'")
        rest = rest.strip()
        i += 1
        if rest == "":
            if i < len(rows) and rows[i][0] > indent:
                out[key], i = _parse_node(rows, i, rows[i][0])
            elif i < len(rows) and rows[i][0] == indent and (
                rows[i][1].startswith("- ") or rows[i][1] == "-"
            ):
                out[key], i = _parse_list(rows, i, indent)
            else:
                out[key] = None
        else:
            out[key] = _scalar(rest)
    return out, i


def _parse_list(rows: List[Tuple[int, str]], i: int, indent: int) -> Tuple[List[Any], int]:
    items: List[Any] = []
    while i < len(rows):
        ind, txt = rows[i]
        if ind != indent or not (txt.startswith("- ") or txt == "-"):
            break
        rest = txt[1:].strip()
        i += 1
        if rest == "":
            if i < len(rows) and rows[i][0] > indent:
                val, i = _parse_node(rows, i, rows[i][0])
                items.append(val)
            else:
                items.append(None)
        else:
            items.append(_scalar(rest))
    return items, i


def loads(text: str) -> Dict[str, Any]:
    rows = _tokenize(text)
    if not rows:
        return {}
    value, _ = _parse_node(rows, 0, rows[0][0])
    return value if isinstance(value, dict) else {}


def load(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return loads(fh.read())


# --------------------------------------------------------------------------- #
# 写入（保留注释与结构，只改目标键的值）
# --------------------------------------------------------------------------- #
def format_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./~\-]+", s) and not re.fullmatch(r"\d+(\.\d+)?", s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _find_key_line(rows: List[Tuple[int, str, str]], path: List[str]) -> int:
    """返回目标键所在行下标；找不到返回 -1。rows = (indent, text, raw)"""
    level = 0
    expect_indent = None
    for idx, (ind, txt, _raw) in enumerate(rows):
        if txt.startswith("-") or ":" not in txt:
            continue
        key = txt.split(":", 1)[0].strip().strip("\"'")
        if expect_indent is not None and ind != expect_indent:
            continue
        if key == path[level]:
            if level == len(path) - 1:
                return idx
            level += 1
            expect_indent = None
            # 下一层：找首个缩进更大的行作为其父级缩进基准
            for j in range(idx + 1, len(rows)):
                if rows[j][0] > ind:
                    expect_indent = rows[j][0]
                    break
            if expect_indent is None:
                return -1
    return -1


def set_value(text: str, dotted_path: str, value: Any) -> str:
    """在原文中就地替换某个键的值，保留注释与其它内容。

    :param dotted_path: 例如 "display.fill_mode"
    :param value: 标量或列表
    :return: 新的文件文本
    """
    path = [p for p in dotted_path.split(".") if p]
    raw_lines = text.splitlines()
    rows: List[Tuple[int, str, str]] = []
    for raw in raw_lines:
        stripped = _strip_comment(raw)
        if not stripped.strip():
            rows.append((-1, "", raw))
            continue
        rows.append((len(stripped) - len(stripped.lstrip(" ")), stripped.strip(), raw))

    idx = _find_key_line(rows, path)
    if idx < 0:
        raise KeyError(f"配置中找不到键：{dotted_path}")

    ind, txt, raw = rows[idx]
    key_part, _, _rest = txt.partition(":")
    prefix = " " * ind + key_part + ":"

    # 保留该行原有行尾注释
    comment = ""
    for k in range(len(raw)):
        if raw[k] == "#" and not raw[max(0, k - 1)] == "\\":
            # 只在引号外才算注释（简化：第一个未转义的 #）
            comment = "  " + raw[k:]
            break

    if isinstance(value, (list, tuple)):
        # 找该键下面已存在的列表项
        start = end = -1
        for j in range(idx + 1, len(rows)):
            jind, jtxt, _ = rows[j]
            if jind > ind and (jtxt.startswith("- ") or jtxt == "-"):
                if start < 0:
                    start = j
                end = j
            elif jind <= ind and jtxt:
                break
        item_indent = " " * (ind + 2)
        new_items = [f"{item_indent}- {format_scalar(v)}" for v in value]
        if start >= 0:
            return "\n".join(raw_lines[:start] + new_items + raw_lines[end + 1 :]) + "\n"
        # 原本是行内列表或空值 → 写成行内列表
        inline = "[" + ", ".join(format_scalar(v) for v in value) + "]"
        raw_lines[idx] = f"{prefix} {inline}{comment}"
        return "\n".join(raw_lines) + "\n"

    raw_lines[idx] = f"{prefix} {format_scalar(value)}{comment}".rstrip()
    return "\n".join(raw_lines) + "\n"


def save(path: str, updates: Dict[str, Any]) -> None:
    """批量就地更新配置文件（保留注释）。"""
    from .atomic import write_text

    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    for k, v in updates.items():
        text = set_value(text, k, v)
    write_text(path, text)
