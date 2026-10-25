#!/usr/bin/env python3
"""岛·壁纸 / DaoPapers · 打包「可分发」.app 的嵌入与压缩步骤

用法（由 scripts/make_app.sh 的 dist 模式调用）：

    python make_dist.py <项目根> <stage目录> embed   # 把运行时/依赖/源码嵌入 bundle
    python make_dist.py <项目根> <stage目录> zip     # 把 stage 压成 DaoPapers.app zip

嵌入后的 bundle 布局（启动器 daopapers_launcher.c 的「嵌入模式」约定）：

    DaoPapers.app/Contents/
      Info.plist / MacOS/DaoPapers / Resources/AppIcon.icns   ← 原有
      Resources/app/            main.py + app/ + ui/ + config.yaml + assets/tray/
      Resources/runtime/        libpython + stdlib（lib/python3.x，裁剪后 ~20M）
      Resources/site-packages/  venv purelib（pyobjc）

设计约束（沙箱适配，与 make_app.sh 一致）：
  · 只做「复制/覆盖写入」，零删除零改名——shutil.copytree(dirs_exist_ok=True)
  · 不用 tempfile、不写隐藏目录
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import zipfile

# stdlib 里对运行应用毫无用处的部分（prefix 自带的 site-packages 绝不能带——
# 那是构建机环境，227M，真正的依赖在 venv purelib 里单独嵌入）
STDLIB_IGNORE = shutil.ignore_patterns(
    "site-packages", "__pycache__", "test", "tests",
    "idlelib", "tkinter", "turtledemo", "ensurepip", "venv",
)
# site-packages 里 pyobjc 自带的测试套件与调试符号（对运行无用）
SP_IGNORE = shutil.ignore_patterns(
    "PyObjCTest", "__pycache__", "*.dSYM", "*.dist-info",
)


def read_version(project_root: str) -> str:
    ns: dict = {}
    src = os.path.join(project_root, "app", "__init__.py")
    with open(src, encoding="utf-8") as fp:
        exec(fp.read(), ns)  # noqa: S102 - 可信的仓库内文件
    return str(ns["__version__"])


def python_prefix() -> str:
    """运行本脚本的解释器的真实 prefix（venv 会透传到真实安装）。
    与 make_app.sh 的 detect_libpython 同一推导规则。"""
    real = os.path.realpath(sys.executable)
    return os.path.dirname(os.path.dirname(real))


def embed(project_root: str, stage: str) -> None:
    res = os.path.join(stage, "Contents", "Resources")
    app_dst = os.path.join(res, "app")
    runtime_dst = os.path.join(res, "runtime")
    sp_dst = os.path.join(res, "site-packages")

    prefix = python_prefix()
    pyver = f"{sys.version_info[0]}.{sys.version_info[1]}"
    libpython = os.path.join(prefix, "lib", f"libpython{pyver}.dylib")
    if not os.path.isfile(libpython):
        sys.exit(f"[make_dist] 找不到 {libpython}——嵌入运行时失败")
    stdlib_src = os.path.join(prefix, "lib", f"python{pyver}")
    if not os.path.isdir(stdlib_src):
        sys.exit(f"[make_dist] 找不到 stdlib：{stdlib_src}")
    sp_src = os.path.join(project_root, ".venv", "lib",
                          f"python{pyver}", "site-packages")
    if not os.path.isdir(sp_src):
        sys.exit(f"[make_dist] 找不到 venv site-packages：{sp_src}")

    # 1) 项目 payload：main.py 按 __file__ 自定位根，数据/缓存/收藏都在根下
    os.makedirs(app_dst, exist_ok=True)
    for name in ("main.py", "app", "ui", "config.yaml"):
        src = os.path.join(project_root, name)
        dst = os.path.join(app_dst, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=False)
        else:
            shutil.copyfile(src, dst)
    # 托盘图标运行时从 <root>/assets/tray 加载，只带这个子目录
    shutil.copytree(os.path.join(project_root, "assets", "tray"),
                    os.path.join(app_dst, "assets", "tray"),
                    dirs_exist_ok=True, symlinks=False)

    # 2) Python 运行时：libpython dylib + 裁剪后的 stdlib
    os.makedirs(os.path.join(runtime_dst, "lib"), exist_ok=True)
    shutil.copyfile(libpython, os.path.join(runtime_dst, "lib",
                                            f"libpython{pyver}.dylib"))
    shutil.copytree(stdlib_src, os.path.join(runtime_dst, "lib", f"python{pyver}"),
                    dirs_exist_ok=True, symlinks=False, ignore=STDLIB_IGNORE)

    # 3) 第三方依赖（pyobjc）
    shutil.copytree(sp_src, sp_dst, dirs_exist_ok=True, symlinks=False,
                    ignore=SP_IGNORE)

    for label, path in (("payload", app_dst), ("runtime", runtime_dst),
                        ("site-packages", sp_dst)):
        total = sum(os.path.getsize(os.path.join(d, f))
                    for d, _, fs in os.walk(path) for f in fs)
        print(f"[make_dist] 嵌入 {label}: {total / 1e6:.1f} MB -> {path}")


def zip_stage(project_root: str, stage: str) -> str:
    version = read_version(project_root)
    build_dir = os.path.dirname(stage)
    out = os.path.join(build_dir, f"DaoPapers-{version}-macOS.zip")
    app_name = "DaoPapers.app"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dirpath, dirnames, filenames in os.walk(stage):
            dirnames.sort()
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, stage)
                arc = f"{app_name}/{rel}"
                st = os.stat(full)
                zi = zipfile.ZipInfo(arc, date_time=time.localtime(st.st_mtime)[:6])
                zi.external_attr = (st.st_mode & 0o7777) << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fp, zf.open(zi, "w") as dst:
                    shutil.copyfileobj(fp, dst, 1024 * 1024)
                n += 1
    size = os.path.getsize(out)
    print(f"[make_dist] {out}: {n} 个文件, {size / 1e6:.1f} MB")
    return out


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[3] not in ("embed", "zip"):
        print(__doc__)
        return 2
    project_root, stage, action = sys.argv[1], sys.argv[2], sys.argv[3]
    if action == "embed":
        embed(project_root, stage)
    else:
        zip_stage(project_root, stage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
