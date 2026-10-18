# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""フィルタリングログ: 直近の通信と、Shoji がそれをどう扱ったか（ブロック・通過・変更など）。

メモリ上だけに保持し、ディスクには保存しない（閲覧履歴を残さないため）。
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque

# action の種類
BLOCKED = "blocked"         # 広告・トラッカーとしてブロック
ALLOWED = "allowed"         # 許可リスト・一時許可・例外ルールで素通し
PASSED = "passed"           # フィルタに一致せず通過
MODIFIED = "modified"       # 追跡パラメーター除去・AMP 転送など書き換え
PASSTHROUGH = "passthrough" # HTTPS を復号せずに通した（中身は見ていない）
PAGE = "page"               # ページに要素非表示・スクリプトレットを適用


class RequestLog:
    def __init__(self, maxlen: int = 3000):
        self._items: deque[dict] = deque(maxlen=maxlen)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.enabled = True

    def add(self, action: str, url: str = "", host: str = "", *, src: str = "proxy", rtype: str = "",
            method: str = "", page: str = "", rule: str = "", cat: str = "", detail: str = "") -> dict | None:
        if not self.enabled:
            return None
        e = {"id": 0, "t": round(time.time(), 3), "src": src, "action": action, "method": method,
             "rtype": rtype, "url": url[:2000], "host": host, "page": page, "rule": rule[:500],
             "cat": cat, "detail": detail[:300], "status": 0}
        with self._lock:
            e["id"] = next(self._ids)
            self._items.append(e)
        return e

    def query(self, since: int = 0, limit: int = 500, action: str = "", q: str = "",
              page: str = "") -> list[dict]:
        """新しい順に返す。since より新しいものだけ（差分取得用）"""
        q = q.lower().strip()
        out = []
        with self._lock:
            items = list(self._items)
        for e in reversed(items):
            if e["id"] <= since:
                break
            if action and e["action"] != action:
                continue
            if page and page not in (e["page"], e["host"]):
                continue
            if q and q not in e["url"].lower() and q not in e["rule"].lower() and q not in e["host"]:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def last_id(self) -> int:
        with self._lock:
            return self._items[-1]["id"] if self._items else 0
