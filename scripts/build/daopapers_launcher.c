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
 * 编译（见 scripts/make_app.sh）：
 *   clang -O2 -o DaoPapers daopapers_launcher.c \
 *     -DDAOPAPERS_PROJECT_ROOT="\"<项目根目录>\"" \
 *     -DDAOPAPERS_LIBPYTHON="\"<libpython3.13.dylib 绝对路径>\"" \
 *     -DDAOPAPERS_SITE_PACKAGES="\"<venv site-packages 绝对路径>\""
 */
#include <dlfcn.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static FILE *diag_fp = NULL;
static char diag_path[4096];

static void diag(const char *msg) {
    if (diag_fp == NULL) {
        /* 诊断日志落在项目 data/logs 下：跟随项目、不占 /tmp、现场可查 */
        snprintf(diag_path, sizeof(diag_path), "%s/data", DAOPAPERS_PROJECT_ROOT);
        mkdir(diag_path, 0755);
        snprintf(diag_path, sizeof(diag_path), "%s/data/logs", DAOPAPERS_PROJECT_ROOT);
        mkdir(diag_path, 0755);
        snprintf(diag_path, sizeof(diag_path), "%s/data/logs/launcher.log",
                 DAOPAPERS_PROJECT_ROOT);
        diag_fp = fopen(diag_path, "a");
    }
    if (diag_fp != NULL) {
        fprintf(diag_fp, "%s\n", msg);
        fflush(diag_fp);
    }
    fprintf(stderr, "岛·壁纸 launcher: %s\n", msg);
}

#ifndef DAOPAPERS_PROJECT_ROOT
#define DAOPAPERS_PROJECT_ROOT "."
#endif
#ifndef DAOPAPERS_LIBPYTHON
#define DAOPAPERS_LIBPYTHON "libpython3.13.dylib"
#endif
#ifndef DAOPAPERS_SITE_PACKAGES
#define DAOPAPERS_SITE_PACKAGES ""
#endif

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
    signal(SIGTERM, on_term);
    signal(SIGINT, on_term);
    diag("launcher main entered");

    /* dlopen 进来的 libpython 感知不到 venv，用 PYTHONPATH 显式补上 */
    if (DAOPAPERS_SITE_PACKAGES[0] != '\0') {
        setenv("PYTHONPATH", DAOPAPERS_SITE_PACKAGES, 1);
    }
    diag("PYTHONPATH set");

    void *lib = dlopen(DAOPAPERS_LIBPYTHON, RTLD_NOW | RTLD_GLOBAL);
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
    py_argv[1] = DAOPAPERS_PROJECT_ROOT "/main.py";
    for (int i = 1; i < argc; i++) {
        py_argv[i + 1] = argv[i];
    }
    diag(py_argv[1]);
    int rc = py_main(n, py_argv);
    diag("Py_BytesMain returned");
    return rc;
}
