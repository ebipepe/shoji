# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""アプリごとの通信の記録（どのアプリが、どこと、どれだけ通信し、どれだけブロックされたか）。

Shoji を経由する通信（Windows のプロキシ設定に従うアプリ）について、接続してきたアプリ（プロセス名）を
調べて数える。閲覧の記録にあたるので、フィルタリングログと同じく**メモリ上だけ**に持ち、
Shoji を終了するか「クリア」で消える。ファイルにも外部にも保存しない。
"""
from __future__ import annotations

import threading
import time
from collections import Counter

MAX_APPS = 300
MAX_HOSTS = 300        # 1 アプリあたりに覚える接続先の数（多すぎたら少ないものから忘れる）


class AppActivity:
    def __init__(self):
        self._lock = threading.Lock()
        self._apps: dict[str, dict] = {}

    def record(self, app: str, host: str, blocked: bool = False, request: bool = True) -> None:
        if not app or not host:
            return
        now = time.time()
        with self._lock:
            a = self._apps.get(app)
            if a is None:
                if len(self._apps) >= MAX_APPS:
                    oldest = min(self._apps, key=lambda k: self._apps[k]["last"])
                    del self._apps[oldest]
                a = self._apps[app] = {"requests": 0, "blocked": 0, "hosts": Counter(),
                                       "blocked_hosts": Counter(), "first": now, "last": now}
            a["last"] = now
            if request:
                a["requests"] += 1
                a["hosts"][host] += 1
                if len(a["hosts"]) > MAX_HOSTS:
                    for h, _ in a["hosts"].most_common()[MAX_HOSTS // 2:]:
                        del a["hosts"][h]
            if blocked:
                a["blocked"] += 1
                a["blocked_hosts"][host] += 1
                if len(a["blocked_hosts"]) > MAX_HOSTS:
                    for h, _ in a["blocked_hosts"].most_common()[MAX_HOSTS // 2:]:
                        del a["blocked_hosts"][h]

    def snapshot(self, top: int = 8) -> list[dict]:
        with self._lock:
            out = [{"app": name, "requests": a["requests"], "blocked": a["blocked"],
                    "hosts": len(a["hosts"]), "top": a["hosts"].most_common(top),
                    "top_blocked": a["blocked_hosts"].most_common(top),
                    "first": int(a["first"]), "last": int(a["last"])}
                   for name, a in self._apps.items()]
        out.sort(key=lambda x: (-x["requests"], x["app"]))
        return out

    def clear(self) -> None:
        with self._lock:
            self._apps.clear()
