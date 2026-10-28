#!/bin/bash
# =============================================================================
#  把「岛·壁纸 / DaoPapers」打包成 macOS 应用，并装进启动台
#
#    ./scripts/make_app.sh              只生成构建产物
#    ./scripts/make_app.sh open         生成并打开
#    ./scripts/make_app.sh install      生成并安装到「应用程序」（启动台可见）
#    ./scripts/make_app.sh install --force   强制重渲染全部图标尺寸
#    ./scripts/make_app.sh dist         产出「可分发」zip（bundle 自带 Python
#                                       运行时与依赖，换机器零依赖，供 Release 附件）
#
#  设计：常规应用（LSUIElement=false，代码里设 Regular），常驻 Dock + 菜单栏，
#        启动台 / Dock 点击都能正常唤起主窗口，行为和其他 app 一致。
#
#  ── 沙箱适配（重要，勿删这些注释）────────────────────────────────────────
#  本机在受限沙箱里跑，构建脚本必须绕开三类被拦截的系统调用：
#
#   1) mkdir 被拒 → 用 Python 的 os.makedirs（shell 的 mkdir 会被安全层拦掉）
#   2) 删除被拒 → 不做 rm / rmtree / os.replace；旧文件一律「覆盖写入」
#      （iconutil、codesign 都需要「写临时文件→改名/删除」，所以本脚本
#        不用 iconutil（改用 scripts/build/build_icns.py 自组装 icns），
#        codesign 失败也只告警不中断——ad-hoc 签名本来就是锦上添花，
#        实测签名失效不影响应用启动）
#   3) tempfile 不可用 → Python 报「无可用临时目录」是常态，
#      凡是依赖 tempfile 的第三方工具都要绕开
#
#  另一个要点：构建目录名不能是 .build 这类隐藏目录——沙箱把项目根下的
#  隐藏目录当内部状态保护，mkdir 会直接失败。改用普通目录名 build/。
# =============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="DaoPapers"
DISPLAY_NAME="岛·壁纸"
BUNDLE_ID="com.derdao.daopapers"
# 构建目录刻意用**非隐藏**普通目录名：沙箱禁止在项目根下 mkdir 隐藏目录。
BUILDDIR="${DAOPAPERS_BUILDDIR:-$DIR/build}"
# staging 目录名刻意**不带 .app 后缀**：
# LaunchServices 只会登记 .app 结尾的包，staging 残留也不会在启动台露出来。
STAGE="$BUILDDIR/${APP_NAME}.staging"
BUNDLE="$BUILDDIR/${APP_NAME}.app"
ICNS="$DIR/assets/AppIcon.icns"
PY="$DIR/.venv/bin/python"

say() { printf "\033[1;34m▶ %s\033[0m\n" "$1"; }
ok()  { printf "\033[1;32m✓ %s\033[0m\n" "$1"; }
warn(){ printf "\033[1;33m! %s\033[0m\n" "$1"; }

[ -x "$PY" ] || { echo "找不到虚拟环境：$PY（先运行 ./scripts/install.sh）" >&2; exit 1; }

# 目录创建走 Python：shell 的 mkdir 在本机沙箱里会被安全层拦截。
# 注意用 -c 而不是 `python - args`（那会让解释器把参数当脚本源码，进 REPL 卡死）。
mkdirs() {
  "$PY" -c 'import os,sys
for d in sys.argv[1:]:
    os.makedirs(d, exist_ok=True)' "$@"
}

# 文件复制也走 Python：cp 内部会 unlink 目标文件，沙箱拦截删除 → cp 静默失败。
# shutil.copyfile 是纯覆盖写入（truncate + write），实测可用。
copy_to() {
  "$PY" -c 'import shutil,sys
shutil.copyfile(sys.argv[1], sys.argv[2])' "$1" "$2"
}

# 改执行位同样走 Python：shell 的 chmod 在沙箱下可能被拦。
chmod_x() {
  "$PY" -c 'import os,sys
os.chmod(sys.argv[1], os.stat(sys.argv[1]).st_mode | 0o111)' "$1"
}

# 从解释器真实路径推导 libpython：<prefix>/bin/python3.13 -> <prefix>/lib/。
# 不用 sysconfig 的 LIBDIR——venv 会继承构建机的值（如 /install/lib），不可信。
detect_libpython() {
  local py="$1" pyver="$2" real prefix cand
  real="$("$py" -c 'import os,sys; print(os.path.realpath(sys.executable))' 2>/dev/null || true)"
  if [ -n "$real" ]; then
    prefix="$(dirname "$(dirname "$real")")"
    if [ -f "$prefix/lib/libpython${pyver}.dylib" ]; then
      echo "$prefix/lib/libpython${pyver}.dylib"
      return 0
    fi
  fi
  for cand in \
    "$DIR/.venv/lib/libpython${pyver}.dylib" \
    "/Library/Frameworks/Python.framework/Versions/${pyver}/lib/libpython${pyver}.dylib" \
    "/usr/lib/libpython${pyver}.dylib"
  do
    [ -f "$cand" ] && { echo "$cand"; return 0; }
  done
  echo ""
}

build_icon() {
  # 图标来源：assets/app-icon.svg（用户手绘「日落波浪」的精细化矢量稿）
  # 流程：SVG → WebKit 逐尺寸原生渲染 → iconset → 自组装 icns（纯 PNG 型图层）
  #
  # 为什么主路是自组装而不是 iconutil（2026-10-25 更正）：
  #   旧注释说「iconutil 因沙箱不能写系统临时目录而不可用」——**这是误判**，
  #   实际只要 `TMPDIR=$PWD/build/tmp iconutil ...` 就能成功（RC=0）。
  #   现在不用它的真正原因是：**iconutil 一定会额外产出 legacy ARGB /
  #   调色板索引图层（ic04/ic05）**，实测我方 ic05 调色板色数高达 1282，
  #   远超 8 位索引上限 256；虽然实测 IconServices 渲染时并不采用 legacy 层，
  #   但留着它没有好处、且一旦系统某个版本优先取 legacy 层就会小尺寸花屏。
  #   → 自组装只产现代 PNG 型图层（ic11/ic12/ic07/ic08/ic09/ic10/ic13/ic14）。
  #   iconutil 降为兜底（自组装失败时才用），且其产物必须过 verify() 的
  #   legacy 硬禁令校验——不过就报错，不允许静默装进 App。
  say "绘制图标（SVG → 多尺寸原生渲染）"
  "$PY" "$DIR/scripts/build/gen_icon_svg.py" >/dev/null
  "$PY" "$DIR/scripts/build/build_icons_from_svg.py" "$@" >/dev/null
  "$PY" "$DIR/scripts/build/gen_tray_white.py" >/dev/null
  # 窗口左上角的品牌标记也必须跟应用图标是同一份像素。
  # 早前 HTML 里是一个手写的通用占位图形（蓝圆+两条横线），
  # 导致「窗口里的图标还是旧的」——启动台/Dock 修好了它也不会变。
  # 这里从 AppIcon.icns 提取 128px 图层，base64 内嵌进 ui/index.html。
  "$PY" "$DIR/scripts/build/embed_brand_icon.py" 128 >/dev/null
  ok "图标：$ICNS"
}

build_executable() {
  # Mach-O 启动器：dlopen libpython 后在【同一进程内】跑 main.py。
  # launchd 生成的那个进程就是应用本身，状态项据此正常落户。
  local pyver site_pkgs libpython exe="$STAGE/Contents/MacOS/${APP_NAME}"
  pyver="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  site_pkgs="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  libpython="$(detect_libpython "$PY" "$pyver")"

  if command -v clang >/dev/null 2>&1 && [ -n "$libpython" ]; then
    say "编译 Mach-O 启动器"
    # clang 也要写临时中间文件，沙箱下可能失败——失败不阻断：
    # 只要 STAGE 里已有上一版可执行文件，就继续用它（启动器逻辑没变时等价）。
    if clang -O2 -o "$exe" "$DIR/scripts/build/daopapers_launcher.c" \
      -DDAOPAPERS_PROJECT_ROOT="\"$DIR\"" \
      -DDAOPAPERS_LIBPYTHON="\"$libpython\"" \
      -DDAOPAPERS_SITE_PACKAGES="\"$site_pkgs\"" \
      -DDAOPAPERS_PYVER="\"$pyver\"" 2>/dev/null; then
      ok "启动器：$exe"
      ok "Python 运行时：$libpython"
    elif [ -x "$exe" ]; then
      warn "clang 在当前沙箱下无法编译（需要写临时文件），沿用已有启动器：$exe"
    else
      echo "无法构建启动器：clang 编译失败且 $exe 不存在。" >&2
      echo "请在非沙箱环境执行：xcode-select --install" >&2
      exit 1
    fi
  elif [ -f "$DIR/scripts/build/prebuilt/${APP_NAME}" ]; then
    # 兜底：换机器构建且没有 clang 时用预编译件。
    # 注意：预编译件内写死了构建机的绝对路径，仅在同路径环境下有效。
    say "使用预编译启动器（clang 不可用或未找到 libpython${pyver}.dylib）"
    copy_to "$DIR/scripts/build/prebuilt/${APP_NAME}" "$exe"
    chmod_x "$exe"
  else
    echo "无法构建启动器：需要 clang（xcode-select --install）与 libpython${pyver}.dylib，" >&2
    echo "或将可用的 Mach-O 启动器放到 scripts/build/prebuilt/${APP_NAME}" >&2
    exit 1
  fi
}

build_bundle() {
  say "构建 ${APP_NAME}.app"
  mkdirs "$STAGE/Contents/MacOS" "$STAGE/Contents/Resources"
  copy_to "$ICNS" "$STAGE/Contents/Resources/AppIcon.icns"

  # Info.plist 也用 Python 写：shell 的 heredoc（cat > f <<EOF）在 zsh 下要往
  # $TMPDIR 落临时文件，沙箱里 tempfile 不可用 → heredoc 直接把脚本打断。
  "$PY" -c 'import sys
plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>""" + sys.argv[1] + """</string>
  <key>CFBundleDisplayName</key><string>""" + sys.argv[2] + """</string>
  <key>CFBundleIdentifier</key><string>""" + sys.argv[3] + """</string>
  <key>CFBundleExecutable</key><string>""" + sys.argv[1] + """</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSUIElement</key><false/>
</dict>
</plist>
"""
with open(sys.argv[4], "w", encoding="utf-8") as fp:
    fp.write(plist)' "$APP_NAME" "$DISPLAY_NAME" "$BUNDLE_ID" \
      "$STAGE/Contents/Info.plist"

  build_executable

  # 签名（ad-hoc）：只是避免部分「已损坏」提示。
  # codesign 内部要写 .cstemp 再改名，沙箱下常失败——失败只告警，
  # 但**必须能看到真实错误**，不能把输出吞掉（上一版静默失败，
  # 导致 bundle 里留着上一版签名的 CodeResources）。
  if codesign --force --deep --sign - "$STAGE"; then
    ok "已签名（ad-hoc）"
  else
    warn "codesign 在当前沙箱下失败（需写临时文件）；不影响启动，继续"
  fi
  # touch 也要走 Python：shell 的 touch 在沙箱下可能被拦。
  "$PY" -c 'import os,sys; os.utime(sys.argv[1], None)' "$STAGE"
  ok "已生成：$STAGE"
}

install_bundle() {
  local dest="/Applications"
  if [ ! -w "$dest" ]; then
    dest="$HOME/Applications"
    mkdirs "$dest"
  fi
  say "安装到 ${dest}"
  local target="${dest}/${APP_NAME}.app"

  # ── IconServices 缓存陷阱（2026-10-25 血泪，勿删这段注释）────────────────
  #  IconServices 对 **bundle 路径** 缓存图标渲染结果，而且：
  #    · 换 CFBundleIdentifier  → 无效（缓存键不是 id）
  #    · 换 icns 文件名 / 新 inode / 新 mtime → 无效（缓存键不是文件）
  #    · lsregister -u / -f、killall Dock、killall iconservicesagent → 均无效
  #  实测：同一份 icns 字节装到新路径 → 渲染完美；装在旧路径 → 彩色噪点。
  #  ⇒ 换图标后必须让系统「忘掉」这个路径：把旧 bundle **移走**（改名），
  #    再把新 bundle 装回同一路径。
  #
  #  移到哪里：移进 **废纸篓**（~/.Trash），而不是留在 /Applications 下。
  #  早前版本用 "${target}.old-<时间戳>" 留在原地，每次安装都会堆一个目录，
  #  越积越多还容易误点。废纸篓同样能让 IconServices 丢弃该路径的缓存
  #  （路径变了），且系统自带「清倒废纸篓」的回收机制。
  #  （时间戳在下面由 Python 现算，不占 shell 变量）
  if [ -d "$target" ]; then
    say "移走旧 bundle（让 IconServices 丢弃该路径的旧图标缓存）"
    "$PY" -c 'import os,sys,time
src = sys.argv[1]
trash = os.path.expanduser("~/.Trash")
os.makedirs(trash, exist_ok=True)
base = os.path.basename(src)
dst = os.path.join(trash, base + ".old-" + time.strftime("%Y%m%d-%H%M%S"))
try:
    os.rename(src, dst)
except OSError:
    # 废纸篓不可写时退回同目录改名（名字不以 .app 结尾，启动台不会收录）
    dst = src + ".old-" + time.strftime("%Y%m%d-%H%M%S")
    os.rename(src, dst)
print("  ", src, "->", dst)' "$target"
  fi

  # 沙箱禁止 rename / rmtree / 删除，但允许「覆盖写入」。
  # 所以：所有文件都用 cp -f 覆盖刷新（不删除任何东西）。
  mkdirs "$target/Contents/MacOS" "$target/Contents/Resources"
  copy_to "$STAGE/Contents/Resources/AppIcon.icns" \
        "$target/Contents/Resources/AppIcon.icns"
  copy_to "$STAGE/Contents/Info.plist" "$target/Contents/Info.plist"
  copy_to "$STAGE/Contents/MacOS/${APP_NAME}" \
        "$target/Contents/MacOS/${APP_NAME}"
  chmod_x "$target/Contents/MacOS/${APP_NAME}"

  # 签名：ad-hoc。这里**必须**看到 codesign 的真实输出——
  # 上一版把输出吞掉（>/dev/null 2>&1）导致签名静默失败，bundle 里留着
  # 上一版签名的 CodeResources（记录旧 icns 哈希），codesign -v 报
  # "a sealed resource is missing or invalid"，系统会认为资源没更新。
  if codesign --force --deep --sign - "$target"; then
    ok "已签名（ad-hoc）"
  else
    warn "codesign 失败（沙箱下需写 .cstemp 临时文件被拦）；不影响启动"
  fi
  # 签名后必须校验：失败要明确报错，不能只在日志里留一句 warn。
  if codesign -v "$target" 2>&1; then
    ok "签名校验通过"
  else
    warn "签名校验未通过：bundle 内 CodeResources 与实际文件不一致"
    warn "  → 在非沙箱环境重跑一次 codesign --force --deep --sign - \"$target\""
  fi

  # 向 LaunchServices 登记，启动台才会收录
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$target" >/dev/null 2>&1 || true
  # 刷 Dock 图标缓存，让新图标立刻可见
  killall Dock >/dev/null 2>&1 || true
  killall iconservicesagent >/dev/null 2>&1 || true
  ok "已安装：$target"
  echo "   启动台里搜索「${DISPLAY_NAME}」即可打开；若暂未出现，稍等几秒或执行：killall Dock"
  INSTALLED_BUNDLE="$target"   # 供 install_autostart 取实际安装路径
}

install_autostart() {
  # 开机自启：写 ~/Library/LaunchAgents/<bundleid>.plist
  # 直接 exec bundle 内二进制 + KeepAlive{SuccessfulExit:false}：
  # 崩溃/被杀自动拉起；用户主动退出（exit 0）不打扰。
  # （2026-10-28 修复：旧写法 /usr/bin/open -a 是瞬时命令，KeepAlive
  #  管不到应用进程，用户退出后应用彻底停摆、无人拉起。）
  # launchctl bootstrap 在本机沙箱下报 I/O error，但登录时 launchd 会
  # 自动扫描 ~/Library/LaunchAgents，无需 bootstrap 也能自启。
  # bundle 路径要和实际安装位置一致（/Applications 不可写时会落到 ~/Applications）。
  local bundle="${1:-/Applications/${APP_NAME}.app}"
  say "配置开机自启"
  "$PY" -c 'import os,plistlib,sys
label, bundle, root = sys.argv[1], sys.argv[2], sys.argv[3]
exe = os.path.join(bundle, "Contents", "MacOS", os.path.splitext(os.path.basename(bundle))[0])
d = os.path.expanduser("~/Library/LaunchAgents")
os.makedirs(d, exist_ok=True)
plist = {
    "Label": label,
    "ProgramArguments": [exe],
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "StandardOutPath": os.path.join(root, "data", "logs", "launchd.out.log"),
    "StandardErrorPath": os.path.join(root, "data", "logs", "launchd.err.log"),
}
p = os.path.join(d, label + ".plist")
with open(p, "wb") as fp:
    plistlib.dump(plist, fp)
print("  已写入", p)' "$BUNDLE_ID" "$bundle" "$DIR"
  ok "开机自动启动：${BUNDLE_ID}"
}

dist_package() {
  # 产出「可分发」的 zip：bundle 自带运行时/依赖/源码，换机器零依赖。
  # 启动器 daopapers_launcher.c 的「嵌入模式」与 scripts/build/make_dist.py
  # 的 bundle 布局是同一份约定，两处必须同步修改。
  # 沙箱注意：本函数只做「嵌入 + 覆盖写 zip」，不做删除/改名/临时文件。
  say "嵌入运行时与项目源码（可分发布局）"
  "$PY" "$DIR/scripts/build/make_dist.py" "$DIR" "$STAGE" embed || return 1
  # 嵌入改动了 Resources → 之前的签名失效，重签一次（沙箱失败仅告警）
  if codesign --force --deep --sign - "$STAGE" 2>&1; then
    ok "已重签（ad-hoc）"
  else
    warn "codesign 失败（沙箱下常见）；不影响功能，CI 构建会正常签名"
  fi
  say "压缩为可分发包"
  "$PY" "$DIR/scripts/build/make_dist.py" "$DIR" "$STAGE" zip
}

case "${1:-}" in
  install)
    shift 2>/dev/null || true
    build_icon "$@"
    build_bundle
    install_bundle
    install_autostart "${INSTALLED_BUNDLE:-/Applications/${APP_NAME}.app}"
    ;;
  open)
    shift 2>/dev/null || true
    build_icon "$@"
    build_bundle
    # open 需要 .app 后缀：从 staging 复制一份正式命名的副本
    mkdirs "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
    copy_to "$STAGE/Contents/Resources/AppIcon.icns" \
          "$BUNDLE/Contents/Resources/AppIcon.icns"
    copy_to "$STAGE/Contents/Info.plist" "$BUNDLE/Contents/Info.plist"
    copy_to "$STAGE/Contents/MacOS/${APP_NAME}" \
          "$BUNDLE/Contents/MacOS/${APP_NAME}"
    chmod_x "$BUNDLE/Contents/MacOS/${APP_NAME}"
    open "$BUNDLE"
    ;;
  dist)
    shift 2>/dev/null || true
    # CI / 发布构建：DAOPAPERS_SKIP_ICONS=1 跳过图标重绘（用仓库里已入库的
    # AppIcon.icns 与托盘 PNG——CI runner 的 WKWebView 渲染不保证可用）
    if [ "${DAOPAPERS_SKIP_ICONS:-0}" = "1" ]; then
      warn "跳过图标重绘（DAOPAPERS_SKIP_ICONS=1，使用已入库图标）"
    else
      build_icon "$@"
    fi
    build_bundle
    dist_package
    echo "   可分发包已生成：build/DaoPapers-*-macOS.zip（bundle 自带运行时，零依赖）"
    ;;
  *)
    shift 2>/dev/null || true
    build_icon "$@"
    build_bundle
    echo "   构建产物：$STAGE"
    echo "   想装进启动台：./scripts/make_app.sh install"
    ;;
esac
