#!/usr/bin/env python3
"""语法检查：不写 pycache（沙箱临时目录受限），只做 AST 解析。

用绝对路径基于项目根推导，不依赖调用时的当前工作目录。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

files = [
    "app/ui/tray.py",
    "app/runner.py",
    "scripts/build/gen_icon_svg.py",
    "scripts/build/gen_tray_white.py",
    "scripts/build/build_icons_from_svg.py",
    "scripts/build/build_icns.py",
    "scripts/build/render_svg.py",
    "scripts/build/strip_png_chunks.py",
    "scripts/build/embed_brand_icon.py",
    "scripts/tools/fit_squircle.py",
    "scripts/tools/analyze_svg_layers.py",
]
bad = 0
for f in files:
    path = os.path.join(ROOT, f)
    try:
        with open(path, encoding="utf-8") as fp:
            ast.parse(fp.read(), filename=f)
        print("  OK  %s" % f)
    except SyntaxError as e:
        bad += 1
        print("  ERR %s: %s" % (f, e))
sys.exit(1 if bad else 0)
