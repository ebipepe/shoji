# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""使っているブラウザが古いままになっていないかを確かめる。

ページを開くだけで攻撃される種類の脆弱性（ブラウザのゼロデイ）への一番の対策は、ブラウザの更新。
Shoji は通信に含まれるブラウザの名前と版（User-Agent）から、使われている Edge / Chrome / Firefox の
版を知ることができる。1 日に 1 回、各社の公式の公開情報から最新の版を取り寄せ、古ければ知らせる。

今のブラウザはプライバシーのため、通信に「大きい版」（例: 156）しか書かない。
そのため分かるのは「大きい版が遅れているか」だけで、細かい修正版（156.0.1234.56）までは確かめられない。

新しい版は、まず一部の利用者にだけ配られ、数日〜数週間かけて全員に広がる（段階的な配信）。
まだ届いていない人に「更新して」と言っても更新できないので、全員に配られた版だけを「最新」として扱う:
- Chrome: Google の公開情報で、配信の割合が 100% になった版
- Edge: 公開から 7 日たった版
- Firefox: Shoji が初めてその版を見てから 7 日たってから知らせる
ただし 2 つ以上遅れていれば、確実に古いのですぐ知らせる。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
import threading
import time
import urllib.request
from typing import Callable, Optional

from . import __version__

# 名前の表示は Edge / Chrome / Firefox。Brave・Vivaldi などは Chrome と同じ表記になるため Chrome として扱う
_EDGE = re.compile(r"\bEdg/(\d+)\.")
_OPERA = re.compile(r"\bOPR/")
_CHROME = re.compile(r"\bChrome/(\d+)\.")
_FIREFOX = re.compile(r"\bFirefox/(\d+)\.")

SOURCES = {
    # 今配信中の正式版（配信の割合 fraction 付き）
    "chrome": "https://versionhistory.googleapis.com/v1/chrome/platforms/win64/channels/stable/versions/all/releases"
              "?filter=endtime=none",
    "edge": "https://edgeupdates.microsoft.com/api/products",
    "firefox": "https://product-details.mozilla.org/1.0/firefox_versions.json",
}
NAMES = {"edge": "Microsoft Edge", "chrome": "Google Chrome", "firefox": "Firefox"}
SEEN_DAYS = 3          # この日数より前に見かけたきりのブラウザは、もう使っていないものとして扱う
REFRESH_HOURS = 24
ROLLOUT_DAYS = 7       # 段階的な配信が終わるまでの目安（Edge・Firefox）


def parse_ua(ua: str) -> Optional[tuple[str, int]]:
    """User-Agent から (ブラウザ, 大きい版)。対象外なら None"""
    if not ua or "Windows" not in ua:
        return None
    m = _EDGE.search(ua)
    if m:
        return "edge", int(m.group(1))
    if _OPERA.search(ua):
        return None
    m = _FIREFOX.search(ua)
    if m:
        return "firefox", int(m.group(1))
    m = _CHROME.search(ua)
    if m:
        return "chrome", int(m.group(1))
    return None


def _major(v) -> Optional[int]:
    m = re.match(r"\s*(\d+)\.", str(v or ""))
    return int(m.group(1)) if m else None


def _published(v) -> float:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def latest_from(name: str, data, now: Optional[float] = None) -> Optional[int]:
    """各社の公開情報（JSON）から、全員に配られた正式版の最新の大きい版を取り出す"""
    now = time.time() if now is None else now
    try:
        if name == "chrome":
            # 配信の割合が 100% になった版だけ（一部の利用者への先行配信中の版は除く）
            vals = [_major(r.get("version")) for r in data.get("releases", [])
                    if float(r.get("fraction") or 0) >= 0.999]
        elif name == "edge":
            vals = [_major(r.get("ProductVersion"))
                    for p in data if str(p.get("Product", "")).lower() == "stable"
                    for r in p.get("Releases", []) if str(r.get("Platform", "")).lower() == "windows"
                    and now - _published(r.get("PublishedTime")) >= ROLLOUT_DAYS * 86400]
        elif name == "firefox":
            vals = [_major(data.get("LATEST_FIREFOX_VERSION"))]
        else:
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    vals = [v for v in vals if v]
    return max(vals) if vals else None


def _fetch_json(url: str, timeout: int = 20):
    # 自分自身のプロキシを通らないよう直接つなぐ（フィルタリストのダウンロードと同じ）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": f"Shoji/{__version__}", "Accept": "application/json"})
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read(4 * 1024 * 1024).decode("utf-8"))


class BrowserWatch:
    def __init__(self, fetch: Callable[[str], object] = _fetch_json):
        self._fetch = fetch
        self._lock = threading.Lock()
        self.seen: dict[str, dict] = {}       # ブラウザ -> {"major": 版, "at": 最後に見た時刻}
        self.latest: dict[str, int] = {}
        self.latest_since: dict[str, float] = {}   # その「最新の版」を初めて見た時刻
        self.checked_at = 0.0
        self._last_ua = ""
        self._last_info: Optional[tuple[str, int]] = None

    def note(self, ua: str) -> None:
        """ページを開く通信の User-Agent を記録する"""
        if not ua:
            return
        if ua != self._last_ua:
            self._last_ua, self._last_info = ua, parse_ua(ua)
        info = self._last_info
        if not info:
            return
        name, major = info
        now = time.time()
        with self._lock:
            s = self.seen.get(name)
            # 同じブラウザの古い版と新しい版が混ざる場合（更新の直後など）は新しい方を使う
            if not s or major >= s["major"] or now - s["at"] > 3600:
                self.seen[name] = {"major": major, "at": now}
            else:
                s["at"] = now

    def refresh(self) -> None:
        """使っているブラウザの最新の版を取り寄せる（使っていないブラウザの分は問い合わせない）"""
        with self._lock:
            names = [n for n, s in self.seen.items() if time.time() - s["at"] < SEEN_DAYS * 86400]
        for name in names:
            try:
                v = latest_from(name, self._fetch(SOURCES[name]))
            except Exception:  # noqa: BLE001  ネットワークの失敗は次の機会に
                v = None
            if v:
                with self._lock:
                    if self.latest.get(name) != v:
                        self.latest_since[name] = time.time()
                    self.latest[name] = v
        self.checked_at = time.time()

    def needs_refresh(self) -> bool:
        age = time.time() - self.checked_at
        with self._lock:
            missing = any(n not in self.latest for n in self.seen)
        # 新しいブラウザを見かけたら早めに（失敗したら 1 時間後に）、そうでなければ 1 日 1 回
        return (missing and age > 3600) or age > REFRESH_HOURS * 3600 or (missing and not self.checked_at)

    def report(self) -> list[dict]:
        """[{name, label, major, latest, outdated}]（最近使われたブラウザだけ）"""
        out = []
        with self._lock:
            for name, s in sorted(self.seen.items()):
                if time.time() - s["at"] > SEEN_DAYS * 86400:
                    continue
                latest = self.latest.get(name)
                behind = latest - s["major"] if latest else 0
                # Firefox は公開の日付が分からないので、Shoji が新しい版を初めて見てから 7 日待つ
                settled = name != "firefox" or time.time() - self.latest_since.get(name, 0) >= ROLLOUT_DAYS * 86400
                out.append({"name": name, "label": NAMES[name], "major": s["major"], "latest": latest,
                            "outdated": behind >= 2 or (behind == 1 and settled)})
        return out


def start_checker(ctx, interval: int = 600) -> threading.Thread:
    """10 分ごとに、取り寄せが必要か確かめる（実際の問い合わせは 1 日 1 回と、新しいブラウザを見かけたとき）"""
    def loop():
        time.sleep(30)
        while True:
            try:
                if ctx.cfg["features"].get("browser_update_check", True) and ctx.browsers.needs_refresh():
                    ctx.browsers.refresh()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True, name="browser-check")
    t.start()
    return t
