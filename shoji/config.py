# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""設定ファイル (config.json) の読み書き。

設定は data/config.json に保存され、各コンポーネントは mtime を監視して
変更があれば自動で再読み込みする（ダッシュボードからの変更が即時反映される）。
"""
from __future__ import annotations

import copy
import json
import re
import os
import sys
import threading
from pathlib import Path

# 読み取り専用のリソース（ルール・画面）。exe 版では展開先（sys._MEIPASS）を指す
BASE_DIR = Path(__file__).resolve().parent.parent
FROZEN = bool(getattr(sys, "frozen", False))


def _default_data_dir() -> Path:
    """設定・統計・証明書の置き場所。
    ソース版はリポジトリ内の data/、exe 版は %LOCALAPPDATA%\\Shoji（書き込み可能な場所）。
    環境変数 SHOJI_DATA で変更できる。"""
    env = os.environ.get("SHOJI_DATA")
    if env:
        return Path(env)
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Shoji"
    return BASE_DIR / "data"


DATA_DIR = _default_data_dir()
LOG_PATH = DATA_DIR / "shoji.log"
LISTS_DIR = DATA_DIR / "lists"
CERT_DIR = DATA_DIR / "certs"
RULES_DIR = BASE_DIR / "rules"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CONFIG_PATH = DATA_DIR / "config.json"
STATS_DB = DATA_DIR / "stats.db"

DEFAULT_SHORTCUTS = {"picker": "Ctrl+Shift+Alt+H", "site_off": "Ctrl+Shift+Alt+P"}
_SHORTCUT_RE = re.compile(r"^(?:(?:Ctrl|Shift|Alt)\+){0,3}(?:[A-Z0-9]|F(?:[1-9]|1[0-2]))$")


def normalize_shortcut(value) -> str | None:
    """"ctrl + shift+h" → "Ctrl+Shift+H"。使えない組み合わせは None（"" は無効化として受け付ける）"""
    s = str(value or "").strip()
    if not s:
        return ""
    parts = [p.strip() for p in s.split("+") if p.strip()]
    if not parts:
        return None
    key = parts[-1].upper()
    mods = {p.capitalize() for p in parts[:-1]}
    if not mods <= {"Ctrl", "Shift", "Alt"} or len(mods) != len(parts) - 1:
        return None
    out = "+".join([m for m in ("Ctrl", "Shift", "Alt") if m in mods] + [key])
    if not _SHORTCUT_RE.match(out):
        return None
    # 修飾キーなしの英数字（ページでの文字入力と衝突）や、Shift だけの組み合わせ（大文字の入力）は使わない
    if not (key.startswith("F") and len(key) > 1) and (not mods or mods == {"Shift"}):
        return None
    return out


DEFAULT_CONFIG: dict = {
    "features": {
        "block_ads": True,              # ブラウザ広告ブロック
        "block_trackers": True,         # トラッカーブロック
        "youtube_ads": True,            # YouTube 等の動画広告ブロック
        "cosmetic": True,               # 要素非表示（広告枠）
        "scriptlets": True,             # スクリプトレット（##+js(...) ルール）
        "collapse_space": True,         # 広告削除後のスペース調整
        "anti_reinsertion": True,       # 再挿入された広告をブロック
        "block_popups": True,           # ポップアップ・ウィンドウの非表示化
        "hide_affiliate_banners": True, # サイトが自前で貼ったアフィリエイトのバナー画像も隠す
        "disable_amp": True,            # AMP の無効化
        "https_filtering": True,        # HTTPS フィルタリング
        "dns_filtering": True,          # DNS フィルタリング（アプリ内広告）
        "cname_uncloaking": True,       # CNAME 偽装トラッカー検出
        "block_malware": True,          # 危険なサイト（マルウェア・フィッシング・採掘）と詐欺ページの対策
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
        # "pac" = 自動構成スクリプト方式（Shoji が止まっていても自動で直接接続に戻る。推奨）
        # "static" = 固定のプロキシ設定（PAC に対応しないアプリも通したい場合）
        "system_proxy_mode": "pac",
    },
    "app": {
        "tray": True,                   # タスクトレイに常駐する
        "open_dashboard_on_start": True,
        "language": "auto",             # 表示言語: auto（Windows の表示言語に従う） / ja / en
        # ページ上のショートカット（"" で無効）。修飾キー Ctrl / Shift / Alt と、英字・数字・F1〜F12
        "shortcuts": dict(DEFAULT_SHORTCUTS),
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
        {"name": "AdGuard DNS filter", "url": "https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt", "category": "ad", "enabled": True, "format": "domains"},
        # 危険なサイト（malware-filter は CC0、NoCoin は MIT）
        {"name": "Malicious URL Blocklist (URLhaus)", "url": "https://malware-filter.gitlab.io/malware-filter/urlhaus-filter-ag-online.txt",
         "category": "security", "enabled": True, "desc": "マルウェアを配布している URL（abuse.ch URLhaus のデータ）",
         "desc_en": "URLs that spread malware (abuse.ch URLhaus data)"},
        {"name": "Phishing URL Blocklist", "url": "https://malware-filter.gitlab.io/malware-filter/phishing-filter-ag.txt",
         "category": "security", "enabled": True, "desc": "フィッシング（偽のログイン画面など）サイト",
         "desc_en": "Phishing sites (fake login pages and similar)"},
        {"name": "NoCoin Filter List", "url": "https://raw.githubusercontent.com/hoshsadiq/adblock-nocoin-list/master/nocoin.txt",
         "mirrors": ["https://cdn.jsdelivr.net/gh/hoshsadiq/adblock-nocoin-list@master/nocoin.txt"],
         "category": "security", "enabled": True, "desc": "ブラウザで勝手に仮想通貨を採掘するスクリプト",
         "desc_en": "Scripts that mine cryptocurrency in your browser"},
        {"name": "Peter Lowe's list", "url": "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=adblockplus&showintro=0&mimetype=plaintext", "category": "ad", "enabled": True, "format": "domains"},
        # 迷惑要素（Annoyances）。表示崩れの可能性があるため、最初はオフ
        {"name": "AdGuard Cookie Notices", "url": "https://filters.adtidy.org/extension/ublock/filters/18.txt", "category": "annoyance", "enabled": False,
         "desc": "Cookie の同意を求めるバナー・ポップアップを隠す",
         "desc_en": "Hides cookie consent banners and pop-ups"},
        {"name": "AdGuard Popups", "url": "https://filters.adtidy.org/extension/ublock/filters/19.txt", "category": "annoyance", "enabled": False,
         "desc": "メールマガジン登録・お知らせ許可などのページ内ポップアップを隠す",
         "desc_en": "Hides in-page pop-ups such as newsletter sign-ups and notification prompts"},
        {"name": "AdGuard Mobile App Banners", "url": "https://filters.adtidy.org/extension/ublock/filters/20.txt", "category": "annoyance", "enabled": False,
         "desc": "「アプリで開く」などスマホアプリへの誘導バナーを隠す",
         "desc_en": "Hides \"open in the app\" banners"},
        {"name": "AdGuard Widgets", "url": "https://filters.adtidy.org/extension/ublock/filters/22.txt", "category": "annoyance", "enabled": False,
         "desc": "チャット・サポート窓口などの外部ウィジェットを隠す",
         "desc_en": "Hides third-party widgets such as chat and support boxes"},
        {"name": "AdGuard Social Media", "url": "https://filters.adtidy.org/extension/ublock/filters/4.txt", "category": "annoyance", "enabled": False,
         "desc": "「いいね」「シェア」などの SNS ボタン・埋め込みを隠す",
         "desc_en": "Hides social buttons and embeds (Like, Share, …)"},
        {"name": "AdGuard Other Annoyances", "url": "https://filters.adtidy.org/extension/ublock/filters/21.txt", "category": "annoyance", "enabled": False,
         "desc": "その他の迷惑な要素（自サイトの宣伝、コピー禁止など）を隠す",
         "desc_en": "Hides other annoyances (self-promotion, copy blocking, …)"},
    ],
    "update_interval_hours": 24,
    # 許可リスト（ここに入れたサイトではフィルタしない）
    "whitelist": [],
    # HTTPS を復号しないホスト（銀行・証明書ピンニングのアプリ等）。サフィックス一致。
    # 利用者が追加する除外先（内蔵の除外先 BUILTIN_HTTPS_EXCLUSIONS は常に適用される）
    "https_exclusions": [],
}

# HTTPS を復号しないサイト（常に適用）。お金・認証情報を扱うサイトと、証明書を厳しく確認する OS/開発系のサービス。
# ドメイン単位のブロック（DNS・CONNECT 時のホスト判定）は引き続き効く。
BUILTIN_HTTPS_EXCLUSIONS: tuple[str, ...] = (
    # OS・アップデート・サインイン
    "apple.com", "icloud.com", "mzstatic.com",
    "windowsupdate.com", "update.microsoft.com", "login.microsoftonline.com", "login.live.com",
    "smartscreen.microsoft.com", "accounts.google.com",
    # Microsoft Store・winget（接続後に証明書を独自に確かめるので、中継すると失敗する）
    "mp.microsoft.com", "winget.microsoft.com", "winget.azureedge.net",
    # パスワード管理・ストレージ
    "dropbox.com", "1password.com", "bitwarden.com", "lastpass.com", "dashlane.com", "keepersecurity.com",
    # 日本の銀行・証券・決済
    "mufg.jp", "smbc.co.jp", "mizuhobank.co.jp", "rakuten-bank.co.jp", "japannetbank.co.jp", "paypay-bank.co.jp",
    "resonabank.co.jp", "sonybank.net", "aeonbank.co.jp", "shinseibank.com", "sbishinseibank.co.jp",
    "netbk.co.jp", "gmo-aozora.com", "jp-bank.japanpost.jp", "jabank.jp", "shinkin.co.jp",
    "sbisec.co.jp", "rakuten-sec.co.jp", "monex.co.jp", "matsui.co.jp", "kabu.com", "kabu.co.jp",
    "nomura.co.jp", "daiwa.jp", "smbcnikko.co.jp", "mizuho-sc.com",
    "paypay.ne.jp", "rakuten-card.co.jp", "smbc-card.com", "jcb.co.jp", "aeon.co.jp",
    "bitbank.cc", "bitflyer.com", "coincheck.com", "gmo-coin.com",
    # 海外の主な銀行・証券・決済
    "paypal.com", "paypalobjects.com", "stripe.com", "stripe.network", "wise.com", "revolut.com",
    "chase.com", "bankofamerica.com", "wellsfargo.com", "citi.com", "citibank.com", "capitalone.com",
    "usbank.com", "pnc.com", "americanexpress.com", "discover.com", "ally.com", "sofi.com",
    "schwab.com", "fidelity.com", "vanguard.com", "etrade.com", "robinhood.com", "interactivebrokers.com",
    "hsbc.com", "hsbc.co.uk", "barclays.co.uk", "lloydsbank.com", "natwest.com", "santander.co.uk",
    "monzo.com", "starlingbank.com", "n26.com", "ing.com", "deutsche-bank.de", "bnpparibas",
    "rbc.com", "td.com", "scotiabank.com", "commbank.com.au", "anz.com", "westpac.com.au", "nab.com.au",
    "coinbase.com", "kraken.com", "binance.com",
    # Claude・開発ツール
    "anthropic.com", "claude.ai", "github.com", "githubusercontent.com",
    "pypi.org", "pythonhosted.org", "npmjs.org",
)


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _with_default_lists(data: dict) -> dict:
    """新しいバージョンで追加された既定のフィルタリストを、保存済みの設定にも加える（有効/無効は既定のまま）"""
    have = {e.get("url") for e in data.get("filter_lists", [])}
    extra = [copy.deepcopy(e) for e in DEFAULT_CONFIG["filter_lists"] if e["url"] not in have]
    if extra:
        data["filter_lists"] = list(data.get("filter_lists", [])) + extra
    # 既定のリストの説明・分類は最新のものを使う
    defaults = {e["url"]: e for e in DEFAULT_CONFIG["filter_lists"]}
    for e in data.get("filter_lists", []):
        d = defaults.get(e.get("url"))
        if d:
            for k in ("desc", "desc_en", "category", "mirrors", "format"):
                if k in d:
                    e[k] = d[k]
    return data


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
            self._data = _with_default_lists(_deep_merge(DEFAULT_CONFIG, user))
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
            self._data = _with_default_lists(_deep_merge(DEFAULT_CONFIG, data))
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
