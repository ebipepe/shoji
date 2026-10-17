# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""設定ファイル (config.json) の読み書き。

設定は data/config.json に保存され、各コンポーネントは mtime を監視して
変更があれば自動で再読み込みする（ダッシュボードからの変更が即時反映される）。
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LISTS_DIR = DATA_DIR / "lists"
CERT_DIR = DATA_DIR / "certs"
RULES_DIR = BASE_DIR / "rules"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CONFIG_PATH = DATA_DIR / "config.json"
STATS_DB = DATA_DIR / "stats.db"

DEFAULT_CONFIG: dict = {
    "features": {
        "block_ads": True,              # ブラウザ広告ブロック
        "block_trackers": True,         # トラッカーブロック
        "youtube_ads": True,            # YouTube 等の動画広告ブロック
        "cosmetic": True,               # 要素非表示（広告枠）
        "collapse_space": True,         # 広告削除後のスペース調整
        "anti_reinsertion": True,       # 再挿入された広告をブロック
        "block_popups": True,           # ポップアップ・ウィンドウの非表示化
        "hide_affiliate_banners": True, # サイトが自前で貼ったアフィリエイトのバナー画像も隠す
        "disable_amp": True,            # AMP の無効化
        "https_filtering": True,        # HTTPS フィルタリング
        "dns_filtering": True,          # DNS フィルタリング（アプリ内広告）
        "cname_uncloaking": True,       # CNAME 偽装トラッカー検出
    },
    "stealth": {
        "enabled": True,
        "strip_tracking_params": True,  # utm_* / fbclid / gclid 等を除去
        "hide_search_queries": True,    # 検索エンジンからのリファラーを除去
        "trim_referer": True,           # サードパーティへのリファラーをオリジンのみに
        "block_third_party_cookies": True,  # トラッカーとの Cookie 送受信を遮断
        "send_dnt": True,               # Do-Not-Track / Global Privacy Control
        "strip_client_hints": True,     # 詳細な OS/ブラウザ情報 (Client Hints) を除去
        "remove_x_client_data": True,   # Chrome の X-Client-Data ヘッダー除去
        "hide_user_agent": False,       # UA を汎用値に置換（互換性に影響するため既定OFF）
        "block_webrtc_leak": True,      # WebRTC によるローカル IP 漏えい防止
        "fingerprint_protection": True, # 画面・ハード情報の解析を妨害
        "first_party_cookie_max_age_hours": 0,  # 0=制限なし。>0 で1stパーティCookie寿命を制限
    },
    "proxy": {
        "listen_host": "127.0.0.1",
        "listen_port": 8080,
        "set_system_proxy": True,       # 起動時に Windows のプロキシ設定を自動変更
    },
    "dns": {
        "listen_host": "127.0.0.1",     # LAN の他端末(スマホ等)からも使う場合は 0.0.0.0
        "listen_port": 53,
        "upstream": "https://cloudflare-dns.com/dns-query",  # DoH または "1.1.1.1"
        "fallback_upstream": "8.8.8.8",
        "block_response": "zero",       # "zero" (0.0.0.0) または "nxdomain"
        "cache_size": 5000,
    },
    "dashboard": {
        "listen_host": "127.0.0.1",
        "listen_port": 8765,
    },
    "filter_lists": [
        {"name": "EasyList", "url": "https://easylist.to/easylist/easylist.txt", "category": "ad", "enabled": True},
        {"name": "EasyPrivacy", "url": "https://easylist.to/easylist/easyprivacy.txt", "category": "tracker", "enabled": True},
        {"name": "AdGuard Japanese", "url": "https://filters.adtidy.org/extension/ublock/filters/7.txt", "category": "ad", "enabled": True},
        {"name": "AdGuard Tracking Protection", "url": "https://filters.adtidy.org/extension/ublock/filters/3.txt", "category": "tracker", "enabled": True},
        {"name": "AdGuard Mobile Ads", "url": "https://filters.adtidy.org/extension/ublock/filters/11.txt", "category": "ad", "enabled": True},
        {"name": "uBlock filters", "url": "https://ublockorigin.github.io/uAssets/filters/filters.txt", "category": "ad", "enabled": True},
        {"name": "uBlock Privacy", "url": "https://ublockorigin.github.io/uAssets/filters/privacy.txt", "category": "tracker", "enabled": True},
        {"name": "AdGuard DNS filter", "url": "https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt", "category": "ad", "enabled": True},
        {"name": "Peter Lowe's list", "url": "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=adblockplus&showintro=0&mimetype=plaintext", "category": "ad", "enabled": True},
    ],
    "update_interval_hours": 24,
    # 許可リスト（ここに入れたサイトではフィルタしない）
    "whitelist": [],
    # HTTPS を復号しないホスト（銀行・証明書ピンニングのアプリ等）。サフィックス一致
    "https_exclusions": [
        "apple.com", "icloud.com", "mzstatic.com",
        "windowsupdate.com", "update.microsoft.com", "login.microsoftonline.com", "login.live.com",
        "smartscreen.microsoft.com", "dropbox.com", "1password.com", "bitwarden.com",
        "mufg.jp", "smbc.co.jp", "mizuhobank.co.jp", "rakuten-bank.co.jp", "japannetbank.co.jp",
        "sbisec.co.jp", "jp-bank.japanpost.jp", "paypay.ne.jp", "bitbank.cc",
        "anthropic.com", "claude.ai", "github.com", "githubusercontent.com",
        "pypi.org", "pythonhosted.org", "npmjs.org",
    ],
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """スレッドセーフな設定ホルダー。get() で常に最新版を返す。"""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._mtime = 0.0
        self._data: dict = copy.deepcopy(DEFAULT_CONFIG)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(self._data)
        self.reload()

    def reload(self) -> bool:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return False
        if mtime == self._mtime:
            return False
        try:
            with open(self.path, encoding="utf-8") as f:
                user = json.load(f)
        except (OSError, ValueError):
            return False
        with self._lock:
            self._data = _deep_merge(DEFAULT_CONFIG, user)
            self._mtime = mtime
        return True

    def get(self) -> dict:
        with self._lock:
            return self._data

    def save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        with self._lock:
            self._data = _deep_merge(DEFAULT_CONFIG, data)
            self._mtime = os.path.getmtime(self.path)

    def update(self, patch: dict) -> dict:
        new = _deep_merge(self.get(), patch)
        self.save(new)
        return new


def is_whitelisted(host: str, whitelist: list[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    for w in whitelist:
        w = w.lower().strip().lstrip("*.").rstrip(".")
        if w and (host == w or host.endswith("." + w)):
            return True
    return False
