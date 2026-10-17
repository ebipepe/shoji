# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""ブロック統計の記録 (SQLite)。

記録はメモリ上でまとめ、数秒ごとに一括書き込みする（高負荷時もボトルネックにならない）。

カテゴリ:
  ad            広告ブロック数
  tracker       トラッカーブロック数
  popup         ポップアップブロック数
  amp           AMP 無効化（正規ページへ転送）数
  reinserted    再挿入広告の除去数
  cosmetic      要素非表示数（ページ側から報告）
  youtube       動画広告の除去数
  stealth_param 追跡パラメーター除去数
  stealth_cookie Cookie 遮断数
  stealth_header 追跡ヘッダー除去数（リファラー/Client Hints 等）
  request       処理したリクエスト総数（ブロック率計算用）
  dns_query     処理した DNS 問い合わせ総数
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path

from .config import STATS_DB

# ブロックしたリソース種別ごとの推定サイズ（バイト）。通信量節約の推計に使う。
EST_BYTES = {
    "script": 45_000,
    "image": 18_000,
    "media": 400_000,   # 動画広告 1 本の最初のセグメント相当
    "sub_frame": 60_000,
    "document": 60_000,
    "xmlhttprequest": 3_000,
    "stylesheet": 12_000,
    "font": 30_000,
    "ping": 500,
    "dns": 25_000,      # DNS でブロックした場合に後続で発生していたであろう通信
    "other": 8_000,
}
# ブロック 1 件あたりの推定短縮時間（ミリ秒）。読み込み速度向上の推計に使う。
EST_MS = {"script": 120, "sub_frame": 250, "media": 5000, "image": 40, "document": 300,
          "dns": 60, "other": 30}

SCHEMA = """
CREATE TABLE IF NOT EXISTS counters (
  day TEXT, category TEXT, source TEXT, count INTEGER DEFAULT 0,
  bytes INTEGER DEFAULT 0, ms INTEGER DEFAULT 0,
  PRIMARY KEY (day, category, source));
CREATE TABLE IF NOT EXISTS hourly (
  hour TEXT, category TEXT, count INTEGER DEFAULT 0,
  PRIMARY KEY (hour, category));
CREATE TABLE IF NOT EXISTS domains (
  day TEXT, domain TEXT, category TEXT, count INTEGER DEFAULT 0,
  PRIMARY KEY (day, domain, category));
CREATE TABLE IF NOT EXISTS recent (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, category TEXT, source TEXT,
  domain TEXT, detail TEXT);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    return con


class Stats:
    def __init__(self, path: Path = STATS_DB, flush_interval: float = 3.0):
        self.path = Path(path)
        self._con = _connect(self.path)
        self._lock = threading.Lock()
        self._counters: dict = defaultdict(lambda: [0, 0, 0])
        self._hourly: dict = defaultdict(int)
        self._domains: dict = defaultdict(int)
        self._recent: list = []
        self._live: dict = defaultdict(int)  # 起動後の累計（ダッシュボードのライブ表示用）
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(flush_interval,),
                                        name="stats-flush", daemon=True)
        self._thread.start()

    # ---- 記録 -------------------------------------------------------------
    def record(self, category: str, source: str, domain: str = "", rtype: str = "other",
               detail: str = "", count: int = 1, count_bytes: bool = True) -> None:
        now = _dt.datetime.now()
        day = now.strftime("%Y-%m-%d")
        hour = now.strftime("%Y-%m-%d %H")
        b = EST_BYTES.get(rtype, EST_BYTES["other"]) * count if count_bytes else 0
        ms = EST_MS.get(rtype, EST_MS["other"]) * count if count_bytes else 0
        with self._lock:
            c = self._counters[(day, category, source)]
            c[0] += count
            c[1] += b
            c[2] += ms
            self._hourly[(hour, category)] += count
            self._live[category] += count
            if domain:
                self._domains[(day, domain.lower(), category)] += count
                if category not in ("request", "dns_query", "cosmetic", "stealth_header"):
                    self._recent.append((time.time(), category, source, domain, detail[:300]))

    def count_request(self, source: str = "proxy") -> None:
        self.record("request" if source == "proxy" else "dns_query", source, count_bytes=False)

    # ---- 書き込み ---------------------------------------------------------
    def flush(self) -> None:
        with self._lock:
            counters, self._counters = self._counters, defaultdict(lambda: [0, 0, 0])
            hourly, self._hourly = self._hourly, defaultdict(int)
            domains, self._domains = self._domains, defaultdict(int)
            recent, self._recent = self._recent, []
        if not (counters or hourly or domains or recent):
            return
        con = self._con
        try:
            with con:
                con.executemany(
                    "INSERT INTO counters(day,category,source,count,bytes,ms) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(day,category,source) DO UPDATE SET count=count+excluded.count, "
                    "bytes=bytes+excluded.bytes, ms=ms+excluded.ms",
                    [(k[0], k[1], k[2], v[0], v[1], v[2]) for k, v in counters.items()])
                con.executemany(
                    "INSERT INTO hourly(hour,category,count) VALUES(?,?,?) "
                    "ON CONFLICT(hour,category) DO UPDATE SET count=count+excluded.count",
                    [(k[0], k[1], v) for k, v in hourly.items()])
                con.executemany(
                    "INSERT INTO domains(day,domain,category,count) VALUES(?,?,?,?) "
                    "ON CONFLICT(day,domain,category) DO UPDATE SET count=count+excluded.count",
                    [(k[0], k[1], k[2], v) for k, v in domains.items()])
                con.executemany(
                    "INSERT INTO recent(ts,category,source,domain,detail) VALUES(?,?,?,?,?)",
                    recent[-500:])
                con.execute("DELETE FROM recent WHERE id < (SELECT MAX(id) FROM recent) - 1000")
        except sqlite3.Error as e:  # 統計の失敗でブロック処理を止めない
            print(f"[stats] write error: {e}")

    def _loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            self.flush()

    def close(self) -> None:
        self._stop.set()
        self.flush()

    def live(self) -> dict:
        with self._lock:
            return dict(self._live)


# ---- レポート (ダッシュボード用・読み取り専用) --------------------------------

def report(days: int | None, path: Path = STATS_DB) -> dict:
    """days=None で全期間。"""
    con = _connect(Path(path))
    try:
        where, args = "", []
        if days:
            since = (_dt.date.today() - _dt.timedelta(days=days - 1)).isoformat()
            where, args = "WHERE day >= ?", [since]
        totals = defaultdict(lambda: {"count": 0, "bytes": 0, "ms": 0})
        by_source = defaultdict(lambda: defaultdict(int))
        for cat, src, cnt, b, ms in con.execute(
                f"SELECT category, source, SUM(count), SUM(bytes), SUM(ms) FROM counters {where} "
                "GROUP BY category, source", args):
            t = totals[cat]
            t["count"] += cnt or 0
            t["bytes"] += b or 0
            t["ms"] += ms or 0
            by_source[cat][src] += cnt or 0
        daily = defaultdict(dict)
        for day, cat, cnt in con.execute(
                f"SELECT day, category, SUM(count) FROM counters {where} GROUP BY day, category "
                "ORDER BY day", args):
            daily[day][cat] = cnt
        top = {}
        for cat in ("ad", "tracker"):
            q_where = (where + " AND" if where else "WHERE") + " category = ?"
            top[cat] = [{"domain": d, "count": c} for d, c in con.execute(
                f"SELECT domain, SUM(count) AS c FROM domains {q_where} GROUP BY domain "
                "ORDER BY c DESC LIMIT 15", args + [cat])]
        today_prefix = _dt.date.today().isoformat()
        hourly = defaultdict(dict)
        for hour, cat, cnt in con.execute(
                "SELECT hour, category, count FROM hourly WHERE hour LIKE ?", [today_prefix + "%"]):
            hourly[hour[-2:]][cat] = cnt
        recent = [dict(zip(("ts", "category", "source", "domain", "detail"), r)) for r in con.execute(
            "SELECT ts, category, source, domain, detail FROM recent ORDER BY id DESC LIMIT 30")]
        blocked_bytes = sum(totals[c]["bytes"] for c in ("ad", "tracker", "popup", "youtube"))
        blocked_ms = sum(totals[c]["ms"] for c in ("ad", "tracker", "popup", "youtube"))
        reqs = totals["request"]["count"] + totals["dns_query"]["count"]
        blocked = totals["ad"]["count"] + totals["tracker"]["count"]
        return {
            "totals": {k: v for k, v in totals.items()},
            "by_source": {k: dict(v) for k, v in by_source.items()},
            "daily": dict(daily),
            "hourly": dict(hourly),
            "top": top,
            "recent": recent,
            "saved_bytes": blocked_bytes,
            "saved_ms": blocked_ms,
            "block_ratio": (blocked / reqs) if reqs else 0.0,
        }
    finally:
        con.close()


def reset(path: Path = STATS_DB) -> None:
    con = _connect(Path(path))
    with con:
        for t in ("counters", "hourly", "domains", "recent"):
            con.execute(f"DELETE FROM {t}")
    con.close()
