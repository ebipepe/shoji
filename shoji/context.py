# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""各コンポーネントで共有する状態（設定・統計・フィルタエンジン）。"""
from __future__ import annotations

import json
import threading
import time

from .config import DATA_DIR, Config, is_whitelisted
from .filters import FilterEngine
from .reqlog import RequestLog
from .stats import Stats


class AppContext:
    def __init__(self, config: Config, stats: Stats, engine: FilterEngine):
        self.config = config
        self.stats = stats
        self.engine = engine
        self.started_at = time.time()
        self.rules_version = str(int(time.time()))
        self._temp_allow: dict[str, float] = {}
        self._lock = threading.Lock()
        # TLS 復号に失敗したホスト（証明書ピンニング等。自動で除外し、ファイルに保存）
        self.passthrough_file = DATA_DIR / "passthrough_hosts.json"
        self.passthrough_hosts: set[str] = self._load_passthrough()
        self._recent_failures: list[tuple[float, str]] = []
        self._tls_ok_hosts: set[str] = set()   # 一度でも正常に復号できたホスト
        # ルート証明書がブラウザに信頼されていることを確認できるまで HTTPS は復号しない
        self.https_ready = False
        self.https_problem = "https.checking"   # i18n のキー
        self.cert_verified = False   # Windows の証明書ストアに登録済みと確認できたか
        # 証明書を受け付けないアプリ（プロセス名）。このアプリの通信は復号しない
        self.untrusting_file = DATA_DIR / "untrusting_apps.json"
        self.untrusting_apps: set[str] = self._load_json_set(self.untrusting_file)
        self.status: dict = {"proxy": "stopped", "dns": "stopped", "lists": None}
        # 一時停止中はフィルタを一切かけず、そのまま通す
        self.paused = False
        self.on_pause_change: list = []
        self.on_ui_change: list = []    # 表示言語など、画面に関わる設定が変わったとき
        self.request_exit = None     # 終了を要求する関数（main が設定する）
        # フィルタリングログ（メモリ上のみ。ディスクには保存しない）
        self.reqlog = RequestLog()

    @property
    def cfg(self) -> dict:
        return self.config.get()

    # ---- Shoji 自身の画面（ブロック画面・確認画面）から許可するときの使い捨てトークン
    # どのページからでも https://shoji.blocker/... を呼べてしまうため、Shoji が表示した画面の
    # ボタンからの操作であることを、画面に埋め込んだトークンで確かめる。
    def issue_token(self, purpose: str, host: str, seconds: int = 900) -> str:
        import secrets
        tok = secrets.token_urlsafe(18)
        now = time.time()
        with self._lock:
            self._tokens = {k: v for k, v in getattr(self, "_tokens", {}).items() if v[2] > now}
            self._tokens[tok] = (purpose, host.lower(), now + seconds)
        return tok

    def use_token(self, tok: str, purpose: str, host: str) -> bool:
        with self._lock:
            v = getattr(self, "_tokens", {}).pop(tok or "", None)
        return bool(v) and v[0] == purpose and v[1] == host.lower() and v[2] > time.time()

    def allow_temporarily(self, host: str, seconds: int = 3600) -> None:
        with self._lock:
            self._temp_allow[host.lower()] = time.time() + seconds

    def is_allowed(self, *hosts: str) -> bool:
        wl = self.cfg.get("whitelist", [])
        now = time.time()
        with self._lock:
            for h in hosts:
                if not h:
                    continue
                if is_whitelisted(h, wl):
                    return True
                exp = self._temp_allow.get(h.lower())
                if exp and exp > now:
                    return True
        return False

    @staticmethod
    def _load_json_set(path) -> set[str]:
        try:
            return set(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return set()

    # 起動のたびに再判定するアプリ（設定で信頼するようになる可能性があるもの）
    _RETRY_APPS = {"firefox.exe", "librewolf.exe", "waterfox.exe", "floorp.exe", "zen.exe",
                   "thunderbird.exe", "msedge.exe", "chrome.exe", "brave.exe", "vivaldi.exe", "opera.exe"}

    def add_untrusting_app(self, proc: str) -> bool:
        with self._lock:
            if proc in self.untrusting_apps:
                return False
            self.untrusting_apps.add(proc)
            persist = sorted(p for p in self.untrusting_apps if p not in self._RETRY_APPS)
        try:
            self.untrusting_file.write_text(json.dumps(persist, indent=1), encoding="utf-8")
        except OSError:
            pass
        return True

    def clear_untrusting_apps(self) -> None:
        with self._lock:
            self.untrusting_apps.clear()
        try:
            self.untrusting_file.write_text("[]", encoding="utf-8")
        except OSError:
            pass

    def _load_passthrough(self) -> set[str]:
        try:
            return set(json.loads(self.passthrough_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return set()

    def _save_passthrough(self) -> None:
        try:
            self.passthrough_file.write_text(json.dumps(sorted(self.passthrough_hosts), indent=1),
                                             encoding="utf-8")
        except OSError:
            pass

    def is_tls_ok(self, host: str) -> bool:
        return host in self._tls_ok_hosts

    def tls_ok(self, host: str) -> None:
        with self._lock:
            if len(self._tls_ok_hosts) < 50000:
                self._tls_ok_hosts.add(host)

    def tls_failed(self, host: str) -> str:
        """ブラウザ/アプリが証明書を拒否したときに呼ぶ。
        戻り値: "host"=そのホストだけ除外 / "global"=証明書自体が信頼されていない / ""=何もしない
        """
        now = time.time()
        with self._lock:
            if not self.https_ready:
                return ""
            self._recent_failures = [(t, h) for t, h in self._recent_failures if now - t < 30]
            self._recent_failures.append((now, host))
            distinct = {h for _, h in self._recent_failures}
            # 短時間に多数のサイトで拒否された = 証明書がインストールされていない/信頼されていない
            if len(distinct) >= 6 and not self.cert_verified:
                self.https_ready = False
                self.https_problem = "https.untrusted"
                for h in distinct:
                    self.passthrough_hosts.discard(h)
                self._recent_failures.clear()
                self._save_passthrough()
                return "global"
            # 他のブラウザでは正常に復号できているホスト = 拒否したのは証明書を読み込まない
            # 特定のアプリ（Firefox 等）なので、ホスト自体は除外しない
            if host in self._tls_ok_hosts:
                return ""
            # 一度も復号に成功していないホストを拒否された = 証明書ピンニングをするアプリ等
            if host not in self.passthrough_hosts:
                self.passthrough_hosts.add(host)
                self._save_passthrough()
                return "host"
        return ""

    def set_https_ready(self, ready: bool, problem: str = "") -> None:
        with self._lock:
            self.https_ready = ready
            self.https_problem = problem
            self._recent_failures.clear()

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        for cb in list(self.on_pause_change):
            try:
                cb(self.paused)
            except Exception:  # noqa: BLE001
                pass

    def rules_reloaded(self) -> None:
        self.rules_version = str(int(time.time()))
