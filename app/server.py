"""内置静态服务：只监听 127.0.0.1，给界面提供图片与页面，不对外暴露。"""

from __future__ import annotations

import http.server
import os
import socket
import socketserver
import threading
from functools import partial

EXTRA_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".heic": "image/heic",
}


class _Handler(http.server.SimpleHTTPRequestHandler):
    root: str = "/"

    def __init__(self, *args, **kwargs):
        kwargs["directory"] = self.root
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):  # 静默，不刷日志
        pass

    def guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in EXTRA_TYPES:
            return EXTRA_TYPES[ext]
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(root: str):
    """在项目根启动静态服务，返回 (base_url, port)。"""
    handler = type("RootHandler", (_Handler,), {"root": root})
    for _ in range(20):
        srv = _Server(("127.0.0.1", 0), handler)
        port = srv.server_address[1]
        try:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return f"http://127.0.0.1:{port}", port, srv
        except OSError:
            srv.server_close()
            continue
    raise RuntimeError("无法启动本地静态服务")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
