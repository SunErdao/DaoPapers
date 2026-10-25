/*
 * 岛·壁纸 / DaoPapers · macOS 启动器（Mach-O，进程内嵌 Python）
 *
 * 为什么需要它：
 *   macOS 26 (Tahoe) 起，Control Center 托管所有第三方 NSStatusItem，并按
 *   「启动者」归因。若 CFBundleExecutable 是 execv 跳转的 trampoline
 *   （shell 包装脚本、C launcher 再 exec 真身等），从启动台 / Finder 启动时
 *   状态项不会被落户——进程照跑、API 调用成功，但图标窗口停在 34x0 永不渲染。
 *   最小复现：github.com/mkrnr/macos-menu-bar-icon-bug-test-project
 *
 * 本启动器是真正的 Mach-O 可执行文件：dlopen libpython 后在【同一进程内】
 * 运行项目 main.py，全程零 execv——launchd 生成的那个进程就是应用本身，
 * 状态项据此正常落户。
 *
 * ── 路径解析（两种模式，运行时自动选择）────────────────────────────────
 *
 *  1) 嵌入模式（可分发，make_app.sh dist 产物）：
 *     启动器用 _NSGetExecutablePath 拿到自身路径，向上探测
 *     <bundle>/Contents/Resources/app/main.py 是否存在。存在则一切以
 *     bundle 内为准：
 *       项目根     <Resources>/app             （main.py 按 __file__ 自定位）
 *       libpython  <Resources>/runtime/lib/libpython<VER>.dylib
 *       PYTHONHOME <Resources>/runtime         （stdlib 在 runtime/lib/python3.x）
 *       PYTHONPATH <Resources>/site-packages   （pyobjc）
 *     bundle 自包含，换机器零依赖。
 *
 *  2) 开发模式（本机构建，make_app.sh 默认产物）：
 *     探测不到嵌入 payload 时回落到下面的编译期宏——行为与旧版完全一致。
 *
 * 编译（见 scripts/make_app.sh）：
 *   clang -O2 -o DaoPapers daopapers_launcher.c \
 *     -DDAOPAPERS_PROJECT_ROOT="\"<项目根目录>\"" \
 *     -DDAOPAPERS_LIBPYTHON="\"<libpython3.13.dylib 绝对路径>\"" \
 *     -DDAOPAPERS_SITE_PACKAGES="\"<venv site-packages 绝对路径>\"" \
 *     -DDAOPAPERS_PYVER="\"3.13\""
 */
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef DAOPAPERS_PROJECT_ROOT
#define DAOPAPERS_PROJECT_ROOT "."
#endif
#ifndef DAOPAPERS_LIBPYTHON
#define DAOPAPERS_LIBPYTHON "libpython3.13.dylib"
#endif
#ifndef DAOPAPERS_SITE_PACKAGES
#define DAOPAPERS_SITE_PACKAGES ""
#endif
#ifndef DAOPAPERS_PYVER
#define DAOPAPERS_PYVER "3.13"
#endif

/* 全局解析结果：diag 与 main 共用。g_root 初值 = 编译期宏（开发模式）。 */
static char g_root[4096] = DAOPAPERS_PROJECT_ROOT;
static char g_libpython[4096] = DAOPAPERS_LIBPYTHON;
static char g_site_packages[4096] = DAOPAPERS_SITE_PACKAGES;
static char g_pythonhome[4096] = "";   /* 仅嵌入模式非空 */

static FILE *diag_fp = NULL;
static char diag_path[4096];

static void diag(const char *msg) {
    if (diag_fp == NULL) {
        /* 诊断日志落在项目 data/logs 下：跟随项目、不占 /tmp、现场可查 */
        snprintf(diag_path, sizeof(diag_path), "%s/data", g_root);
        mkdir(diag_path, 0755);
        snprintf(diag_path, sizeof(diag_path), "%s/data/logs", g_root);
        mkdir(diag_path, 0755);
        snprintf(diag_path, sizeof(diag_path), "%s/data/logs/launcher.log",
                 g_root);
        diag_fp = fopen(diag_path, "a");
    }
    if (diag_fp != NULL) {
        fprintf(diag_fp, "%s\n", msg);
        fflush(diag_fp);
    }
    fprintf(stderr, "岛·壁纸 launcher: %s\n", msg);
}

/* 文件存在性探测（目录/文件均可，不存在返回 0） */
static int path_ok(const char *p) {
    struct stat st;
    return stat(p, &st) == 0;
}

/*
 * 运行时解析路径。嵌入模式（bundle 自带 payload）优先，探测不到则保持
 * 编译期默认值不变（开发模式）。任何一步失败都安全回落，绝不崩溃。
 */
static void resolve_paths(void) {
    char *slash;
    char res[4096];
    char cand[4096];

    /* 拿自身可执行文件路径。第一次传 NULL buffer 是「探测所需大小」的标准
     * 用法，此时返回值**必然非 0**（不是失败）——只要 sz 被写入即可。
     * （2026-10-25 实测踩坑：把首次返回非 0 当成失败，嵌入模式永远不触发，
     *  解压出的 bundle 全部回落 development 模式。） */
    uint32_t sz = 0;
    _NSGetExecutablePath(NULL, &sz);
    if (sz == 0 || sz > 4096) return;
    char *exe = (char *)malloc(sz);
    if (exe == NULL) return;
    if (_NSGetExecutablePath(exe, &sz) != 0) { free(exe); return; }

    /* exe = <bundle>/Contents/MacOS/<name> → 去掉最后一段得 Contents/MacOS */
    slash = strrchr(exe, '/');
    if (slash == NULL) { free(exe); return; }
    *slash = '\0';
    /* Resources 目录：Contents/MacOS 的上一级 */
    snprintf(res, sizeof(res), "%s/../Resources", exe);
    free(exe);

    /* 嵌入模式的判定物：Resources/app/main.py 必须真实存在 */
    snprintf(cand, sizeof(cand), "%s/app/main.py", res);
    if (!path_ok(cand)) return;   /* 开发模式：保持编译期默认值 */

    /* ── 嵌入模式：五项全部改指 bundle 内 ── */
    snprintf(g_root, sizeof(g_root), "%s/app", res);
    snprintf(g_libpython, sizeof(g_libpython), "%s/runtime/lib/libpython%s.dylib",
             res, DAOPAPERS_PYVER);
    /* libpython 是硬依赖：嵌入运行时缺失（打包不完整）时整个回落开发模式 */
    if (!path_ok(g_libpython)) {
        snprintf(g_root, sizeof(g_root), "%s", DAOPAPERS_PROJECT_ROOT);
        snprintf(g_libpython, sizeof(g_libpython), "%s", DAOPAPERS_LIBPYTHON);
        return;
    }
    snprintf(g_site_packages, sizeof(g_site_packages), "%s/site-packages", res);
    if (!path_ok(g_site_packages)) g_site_packages[0] = '\0';
    snprintf(g_pythonhome, sizeof(g_pythonhome), "%s/runtime", res);
}

typedef int (*py_bytes_main_fn)(int, char **);

/* SIGTERM/SIGINT 必须在 C 层接：Python 的信号 handler 只在主线程执行字节码时
 * 触发，而 AppKit 的 app.run() 停在 C 层事件循环里——纯 Python 注册的 handler
 * 对常驻进程毫无作用，kill 发出去进程装死，flock 单实例锁永不释放，
 * 后续所有启动都被误判「已在运行」（2026-10-25 实测踩坑）。
 * C 层 handler 由内核在信号到达时直接调用，与 run loop 无关。 */
static void on_term(int sig) {
    (void)sig;
    _exit(0);
}

int main(int argc, char **argv) {
    char script[4096];
    signal(SIGTERM, on_term);
    signal(SIGINT, on_term);

    /* 先解析路径再写日志：嵌入模式下诊断日志跟随 bundle 内项目根 */
    resolve_paths();
    diag(g_pythonhome[0] != '\0' ? "mode: embedded (bundle self-contained)"
                                 : "mode: development (compile-time paths)");

    /* dlopen 进来的 libpython 感知不到 venv，用 PYTHONPATH 显式补上；
     * 嵌入模式还需 PYTHONHOME 指向 bundle 内运行时（否则 Python 按编译期
     * prefix 找 stdlib，在用户机器上必然找不到） */
    if (g_pythonhome[0] != '\0') {
        setenv("PYTHONHOME", g_pythonhome, 1);
    }
    if (g_site_packages[0] != '\0') {
        setenv("PYTHONPATH", g_site_packages, 1);
    }
    diag("PYTHONHOME/PYTHONPATH set");

    void *lib = dlopen(g_libpython, RTLD_NOW | RTLD_GLOBAL);
    if (lib == NULL) {
        diag("dlopen failed");
        fprintf(stderr, "岛·壁纸：无法加载 Python 运行时：%s\n", dlerror());
        return 1;
    }
    diag("dlopen ok");
    py_bytes_main_fn py_main = (py_bytes_main_fn)dlsym(lib, "Py_BytesMain");
    if (py_main == NULL) {
        diag("dlsym Py_BytesMain failed");
        fprintf(stderr, "岛·壁纸：Python 运行时缺少 Py_BytesMain\n");
        return 1;
    }
    diag("dlsym ok, entering Py_BytesMain");

    /* argv 契约与 main() 相同：argv[0] 程序名，argv[1] 脚本路径，用户参数随后
        （--once / --window / --version 等，从终端直跑时可透传）。
       只传一个参数会进交互式 REPL（进程挂住等 stdin）。 */
    int n = argc + 1;
    char **py_argv = (char **)calloc((size_t)n + 1, sizeof(char *));
    if (py_argv == NULL) {
        fprintf(stderr, "岛·壁纸：内存不足\n");
        return 1;
    }
    py_argv[0] = "DaoPapers";
    snprintf(script, sizeof(script), "%s/main.py", g_root);
    py_argv[1] = script;
    for (int i = 1; i < argc; i++) {
        py_argv[i + 1] = argv[i];
    }
    diag(py_argv[1]);
    int rc = py_main(n, py_argv);
    diag("Py_BytesMain returned");
    return rc;
}
