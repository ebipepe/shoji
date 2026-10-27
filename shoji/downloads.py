# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""危険な種類のファイルのダウンロードを、保存する前に確認する。

対象は、Windows で開くとすぐにプログラムとして動き、ふつうの利用者にはまず必要のない形式
（.hta・.js・.vbs・.lnk・.scr・.bat・.ps1 など）。ウイルスを送り込む入口としてよく使われる。
.exe・.msi は正規の配布が多く、Windows の SmartScreen も確かめるので対象にしない。
ページが読み込んで使うスクリプト（<script src="x.js">）は「ダウンロード」ではないので対象にしない。
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from typing import Optional
from urllib.parse import unquote, urlsplit

DANGEROUS_EXT = frozenset({
    # スクリプト・アプリ（ダブルクリックで実行される）
    "hta", "js", "jse", "vbs", "vbe", "wsf", "wsh", "ps1", "psm1", "bat", "cmd", "msh", "scr", "pif", "cpl",
    "msc", "jar", "jnlp", "gadget", "application", "appref-ms",
    # ショートカット・設定（開くと別のプログラムやコマンドを動かせる）
    "lnk", "url", "scf", "library-ms", "search-ms", "searchconnector-ms", "settingcontent-ms", "reg", "inf",
    # ヘルプ・Office の古い形式（スクリプトやコマンドを含められる）
    "chm", "xll", "iqy", "slk",
})
# ブラウザが画面に表示する（保存しない）種類。添付扱い（attachment）でなければダウンロードではない
_INLINE_TYPES = ("text/", "image/", "audio/", "video/", "application/javascript", "application/x-javascript",
                 "application/ecmascript", "application/json", "application/xml", "application/pdf",
                 "application/xhtml+xml", "application/wasm", "font/")
_FILENAME_STAR = re.compile(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", re.I)
_FILENAME = re.compile(r"filename\s*=\s*(\"([^\"]*)\"|[^;]+)", re.I)


def filename_from(content_disposition: str, url: str) -> str:
    m = _FILENAME_STAR.search(content_disposition or "")
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = _FILENAME.search(content_disposition or "")
    if m:
        return (m.group(2) if m.group(2) is not None else m.group(1)).strip().strip('"')
    path = urlsplit(url).path
    return unquote(path.rsplit("/", 1)[-1])


def extension(name: str) -> str:
    name = name.strip().rstrip(". ").lower()      # "x.hta." や "x.hta " も Windows では .hta
    return name.rsplit(".", 1)[-1] if "." in name else ""


def dangerous_download(url: str, rtype: str, content_type: str, content_disposition: str) -> Optional[str]:
    """危険な種類のファイルのダウンロードなら、そのファイル名を返す"""
    cd = (content_disposition or "").lower()
    attach = cd.startswith("attachment") or ("filename" in cd and not cd.startswith("inline"))
    if not attach:
        # 添付扱いでなくても、ページとして開いた先が保存される種類なら、ブラウザはダウンロードする
        if rtype not in ("document", "sub_frame"):
            return None
        ct = (content_type or "").split(";")[0].strip().lower()
        if not ct or ct.startswith(_INLINE_TYPES):
            return None
    name = filename_from(content_disposition, url)
    return name if extension(name) in DANGEROUS_EXT else None


class DownloadGate:
    """確認画面の「それでもダウンロード」で、そのファイルだけ 1 回通すための記録"""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[str, str, float]] = {}   # id -> (URL, ファイル名, 期限)
        self._allowed: dict[str, float] = {}                    # URL -> 期限

    def hold(self, url: str, name: str) -> str:
        now = time.time()
        i = secrets.token_urlsafe(12)
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if v[2] > now}
            if len(self._pending) > 500:
                self._pending.clear()
            self._pending[i] = (url, name, now + 1800)
        return i

    def pending(self, i: str) -> Optional[tuple[str, str]]:
        with self._lock:
            v = self._pending.get(i or "")
        return (v[0], v[1]) if v and v[2] > time.time() else None

    def allow(self, i: str) -> Optional[str]:
        with self._lock:
            v = self._pending.pop(i or "", None)
            if not v or v[2] < time.time():
                return None
            self._allowed[v[0]] = time.time() + 120
        return v[0]

    def consume(self, url: str) -> bool:
        with self._lock:
            exp = self._allowed.pop(url, 0)
        return exp > time.time()
