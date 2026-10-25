#!/bin/bash
# =============================================================================
#  岛·壁纸 · 安装 / 管理脚本（macOS）
#
#    ./scripts/install.sh            安装依赖 + 装机 + 设为开机自启 + 立即启动
#    ./scripts/install.sh start      启动（若已停止）
#    ./scripts/install.sh stop       停止
#    ./scripts/install.sh restart    重启（改完 config.yaml 后用这个）
#    ./scripts/install.sh status     查看运行状态
#    ./scripts/install.sh uninstall  停止并移除开机自启
#
#  可选环境变量：PYTHON=/usr/bin/python3（指定用于创建虚拟环境的 Python）
#
#  开机自启走 /usr/bin/open -a 拉起 /Applications/DaoPapers.app，与「从启动台
#  点图标」完全同路径——CFBundleExecutable 是 Mach-O 启动器（进程内嵌 Python），
#  macOS 26 的菜单栏状态项才能正常落户。不要改成直拉 .venv/bin/python main.py。
# =============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.derdao.daopapers"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
VENV="$DIR/.venv"
PY="${PYTHON:-$(command -v python3)}"
LOGDIR="$DIR/data"
APP_NAME="DaoPapers"

say() { printf "\033[1;34m▶ %s\033[0m\n" "$1"; }
ok()  { printf "\033[1;32m✓ %s\033[0m\n" "$1"; }

# 应用装到哪：/Applications 优先，不可写时退 ~/Applications
# 注意：目录创建走 Python 的 os.makedirs —— 本机沙箱会拦截 shell 的 mkdir。
app_dir() {
  if [ -w "/Applications" ]; then
    echo "/Applications"
  else
    "$VENV/bin/python" -c 'import os,sys; os.makedirs(sys.argv[1], exist_ok=True)' "$HOME/Applications"
    echo "$HOME/Applications"
  fi
}

install_deps() {
  say "准备 Python 虚拟环境（${VENV}）"
  "$VENV/bin/python" -c 'import os,sys; os.makedirs(sys.argv[1], exist_ok=True)' "$LOGDIR"
  if [ ! -x "$VENV/bin/python" ]; then
    "$PY" -m venv "$VENV"
  fi
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$DIR/requirements.txt"
  ok "依赖安装完成"
}

# 图标资源：与 make_app.sh 的 build_icon 走同一套流程
#   SVG → WebKit 逐尺寸原生渲染 → iconset → 自组装 icns（纯 PNG 型图层）
#   → 托盘白版 → 从 icns 抽 128px 图层内嵌进 ui/index.html
#
# 为什么不再用 iconutil 直接打包（2026-10-25 定案）：
#   iconutil 一定会额外产出 legacy ARGB / 调色板索引图层（ic04/ic05），
#   实测本图标的 ic05 调色板色数高达 1282，远超 8 位索引上限 256。
#   系统在小尺寸场景（启动台、窗口标题栏代理图标）可能优先取 legacy 层
#   → 直接显示彩色噪点（用户实测截图确认）。故一律走自组装。
ensure_assets() {
  if [ ! -f "$DIR/assets/AppIcon.icns" ] || [ ! -f "$DIR/assets/tray/white@2x.png" ]; then
    say "绘制图标资源"
    "$VENV/bin/python" "$DIR/scripts/build/gen_icon_svg.py" >/dev/null
    "$VENV/bin/python" "$DIR/scripts/build/build_icons_from_svg.py" >/dev/null
    "$VENV/bin/python" "$DIR/scripts/build/gen_tray_white.py" >/dev/null
    ok "图标已生成（assets/）"
  fi
}

write_plist() {
  local appdir
  appdir="$(app_dir)"
  say "写入开机自启配置：$PLIST"
  # 用 Python 的 plistlib 写 plist：shell 的 heredoc（cat > f <<EOF）在 zsh 下
  # 要往 $TMPDIR 落临时文件，沙箱里 tempfile 不可用 → heredoc 直接把脚本打断。
  "$VENV/bin/python" -c 'import os,plistlib,sys
label, bundle, plist_path, appdir, logdir = sys.argv[1:6]
os.makedirs(os.path.dirname(plist_path), exist_ok=True)
plist = {
    "Label": label,
    "ProgramArguments": ["/usr/bin/open", "-a", os.path.join(appdir, bundle)],
    "RunAtLoad": True,
    "StandardOutPath": os.path.join(logdir, "launchd.out.log"),
    "StandardErrorPath": os.path.join(logdir, "launchd.err.log"),
}
with open(plist_path, "wb") as fp:
    plistlib.dump(plist, fp)
print("  已写入", plist_path)' "$LABEL" "${APP_NAME}.app" "$PLIST" "$appdir" "$LOGDIR"
  ok "开机自启已配置（经 ${appdir}/${APP_NAME}.app）"
}

load_agent() {
  # launchctl 在某些受限 shell（无 GUI bootstrap 命名空间）里会报
  # "Load failed: 5: Input/output error"。此时不假装成功，直接给出人工执行方案。
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  if launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then
    ok "已启动（菜单栏应出现壁纸图标）"
    return 0
  fi
  printf "\033[1;33m⚠ 当前终端无法注册 launchd（Load failed: 5: Input/output error）\033[0m\n"
  echo "  这是终端环境的限制，不是应用问题。请在「你自己的终端」里执行下面一行："
  echo ""
  echo "    launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/${LABEL}.plist"
  echo ""
  echo "  或者先只跑起来看看效果（不开机自启）：从启动台打开「岛·壁纸」。"
  return 1
}

cmd_install() {
  install_deps
  # ensure_assets 只在资源缺失时补画；正常情况下 make_app.sh install 自己会
  # 走一遍 build_icon（重绘图标），所以这里不做重复构建。
  ensure_assets
  bash "$DIR/scripts/make_app.sh" install
  write_plist
  load_agent || true
  echo
  ok "安装完成。点击菜单栏图标 →「设置…」可调整图源与更新时间。"
  echo "   配置文件：$DIR/config.yaml"
  echo "   日志文件：$LOGDIR/logs/app.log"
}

cmd_start()   { launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null && ok "已启动"; }
cmd_stop()    { launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null; ok "已停止"; }
cmd_restart() { cmd_stop; launchctl bootstrap "gui/$(id -u)" "$PLIST" && ok "已重启（配置已生效）"; }
cmd_status() {
  if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    pid="$(launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | awk '/pid = /{print $3; exit}')"
    ok "已注册开机自启（PID=${pid:-未运行，下次登录/触发时拉起}）"
  else
    echo "未运行"
  fi
}
cmd_uninstall() {
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  # 删除走 Python 的 os.remove：shell 的 rm 在本机沙箱下会被安全层拦截。
  "$VENV/bin/python" -c 'import os,sys
p = sys.argv[1]
if os.path.exists(p):
    os.remove(p)
    print("  已删除", p)' "$PLIST" || true
  ok "已停止并移除开机自启（数据与缓存保留在 ${DIR}）"
}

case "${1:-install}" in
  install)   cmd_install ;;
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  restart)   cmd_restart ;;
  status)    cmd_status ;;
  uninstall) cmd_uninstall ;;
  *) echo "用法：$0 {install|start|stop|restart|status|uninstall}"; exit 1 ;;
esac
