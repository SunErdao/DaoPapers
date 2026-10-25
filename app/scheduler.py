"""调度器：每天固定时间 / 按间隔 / 开机触发更换。

用「轮询对时」而不是定时器，这样系统休眠唤醒后也能正确补触发，不丢任务。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Callable, List


class Scheduler:
    def __init__(self, get_times: Callable[[], List[str]],
                 get_interval: Callable[[], int],
                 on_tick: Callable[[str], None],
                 check_seconds: int = 30):
        self.get_times = get_times
        self.get_interval = get_interval
        self.on_tick = on_tick
        self.check_seconds = check_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread = None
        self._last_day = ""
        self._fired: set = set()
        self._last_interval_fire = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.check_seconds):
            try:
                self._check()
            except Exception:  # 调度循环永不因异常退出
                pass

    def _check(self) -> None:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if today != self._last_day:
            self._last_day = today
            self._fired.clear()

        interval = self.get_interval()
        if interval and interval > 0:
            now_ts = time.time()
            if now_ts - self._last_interval_fire >= interval * 60:
                self._last_interval_fire = now_ts
                self.on_tick("interval")
            return

        hhmm = now.strftime("%H:%M")
        for t in self.get_times():
            if t == hhmm and t not in self._fired:
                self._fired.add(t)
                self.on_tick(f"scheduled:{t}")

    def next_fire_hint(self) -> str:
        interval = self.get_interval()
        if interval and interval > 0:
            remain = max(0, int(interval * 60 - (time.time() - self._last_interval_fire)))
            return f"{remain // 60} 分 {remain % 60} 秒后"
        now = datetime.now()
        times = sorted(self.get_times())
        for t in times:
            try:
                h, m = (int(x) for x in t.split(":"))
            except ValueError:
                continue
            if (h, m) > (now.hour, now.minute):
                return f"今天 {t}"
        return f"明天 {times[0]}" if times else "未设置"
