#!/usr/bin/env python3
"""岛·壁纸 / DaoPapers · 入口

    python3 main.py            启动常驻应用（菜单栏 + 后台定时更换）
    python3 main.py --once     只换一张壁纸就退出（不驻留，适合调试/配合 cron）
    python3 main.py --version  查看版本
"""

from __future__ import annotations

import fcntl
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import __version__  # noqa: E402
from app.runner import run  # noqa: E402

# 单实例锁的文件句柄：进程存活期间必须持有，退出时内核自动释放 flock
_INSTANCE_LOCK = None


def _ensure_single_instance(root: str) -> bool:
    """GUI 常驻模式单实例。

    旧实现在 bundle 的 sh 脚本里用 pgrep 匹配 main.py：Mach-O 启动器改造后
    进程命令行已不含该字符串（pgrep 失效），且 pgrep 会误匹配编辑器等场景。
    flock 由内核保证：进程退出（含被 kill）时锁自动释放，无僵尸匹配。
    返回 False 表示已有实例在跑。
    """
    global _INSTANCE_LOCK
    data_dir = os.path.join(root, "data")
    try:
        os.makedirs(data_dir, exist_ok=True)
        # 必须用 "a"（append）不能用 "w"：被挡实例的退出路径也会 open 一次，
        # "w" 的 truncate 会把持锁实例写入的 pid 擦成 0 字节（2026-10-25 踩坑）。
        fp = open(os.path.join(data_dir, ".instance.lock"), "a")
    except OSError:
        return True  # 锁文件都建不起时不拦启动，降级放行
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fp.close()
        return False
    _INSTANCE_LOCK = fp
    # 持锁者独占记录：回到文件头重写，避免 append 留下历史 pid 误导排查
    # （"a" 模式保证不 truncate 别人的记录；seek+truncate 只发生在拿到锁之后）
    fp.seek(0)
    fp.truncate()
    fp.write(f"{os.getpid()}\n")
    fp.flush()
    return True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv:
        print(f"岛·壁纸 / DaoPapers {__version__}")
        return 0
    once = "--once" in argv or "--no-gui" in argv
    if not once and not _ensure_single_instance(ROOT):
        # 已有实例在跑：唤起它的主窗口后安静退出（runner.pollActivate_ 的契约）
        try:
            open(os.path.join(ROOT, "data", ".activate"), "w").close()
        except OSError:
            pass
        return 0
    return run(ROOT, once=once, open_window="--window" in argv)


if __name__ == "__main__":
    sys.exit(main())
