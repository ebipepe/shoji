# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""ブロックした通信の代わりに返す「代替品」（$redirect / $redirect-rule）。

広告や計測のスクリプトを単にブロックすると、それを呼び出すページ側のコードが止まって
「ボタンが動かない」「動画が始まらない」などの不具合になることがある。
代わりに、何も送らない小さな代替スクリプトを返して、ページを壊さずに済ませる。

代替品はすべて Shoji 独自の実装（assets/redirects/）。名前は uBlock Origin・AdGuard・Adblock Plus の
フィルターリストで使われる呼び名を受け付ける。
"""
from __future__ import annotations

import re
import struct
import zlib
from functools import lru_cache
from typing import Optional

from .config import ASSETS_DIR

_DIR = ASSETS_DIR / "redirects"

JS = "application/javascript; charset=utf-8"


def _png(w: int, h: int) -> bytes:
    """透明な PNG 画像"""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# 1x1 の透明 GIF
GIF_1x1 = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
           b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")

_VAST = '<?xml version="1.0" encoding="UTF-8"?><VAST version="{v}"></VAST>'
_VMAP = ('<?xml version="1.0" encoding="UTF-8"?>'
         '<vmap:VMAP xmlns:vmap="http://www.iab.net/videosuite/vmap" version="1.0"></vmap:VMAP>')
_HTML = '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body></body></html>'


def _misc_parts() -> dict[str, str]:
    text = (_DIR / "misc.js").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^//== (\S+)\n(.*?)(?=^//== |\Z)", text, re.S | re.M):
        out[m.group(1)] = m.group(2)
    return out


@lru_cache(maxsize=None)
def _resources() -> dict[str, tuple[str, bytes]]:
    misc = _misc_parts()

    def js_file(name: str) -> tuple[str, bytes]:
        return JS, (_DIR / name).read_bytes()

    def js_misc(name: str) -> tuple[str, bytes]:
        return JS, misc[name].encode("utf-8")

    return {
        "noop.js": js_misc("noop.js"),
        "noop.txt": ("text/plain; charset=utf-8", b""),
        "noop.css": ("text/css; charset=utf-8", b""),
        "noop.json": ("application/json; charset=utf-8", b"{}"),
        "noop.html": ("text/html; charset=utf-8", _HTML.encode()),
        "1x1.gif": ("image/gif", GIF_1x1),
        "2x2.png": ("image/png", _png(2, 2)),
        "3x2.png": ("image/png", _png(3, 2)),
        "32x32.png": ("image/png", _png(32, 32)),
        "noop-0.1s.mp3": ("audio/mpeg", (_DIR / "noop-0.1s.mp3").read_bytes()),
        "noop-1s.mp4": ("video/mp4", (_DIR / "noop-1s.mp4").read_bytes()),
        "noop-vast2.xml": ("application/xml", _VAST.format(v="2.0").encode()),
        "noop-vast3.xml": ("application/xml", _VAST.format(v="3.0").encode()),
        "noop-vast4.xml": ("application/xml", _VAST.format(v="4.0").encode()),
        "noop-vmap1.xml": ("application/xml", _VMAP.encode()),
        "google-analytics.js": js_file("google-analytics.js"),
        "google-analytics-ga.js": js_file("google-analytics-ga.js"),
        "googletagmanager.js": js_file("googletagmanager.js"),
        "googlesyndication-adsbygoogle.js": js_file("googlesyndication-adsbygoogle.js"),
        "googletagservices-gpt.js": js_file("googletagservices-gpt.js"),
        "google-ima.js": js_file("google-ima.js"),
        "fingerprint2.js": js_misc("fingerprint2.js"),
        "fingerprint3.js": js_misc("fingerprint3.js"),
        "fuckadblock.js": js_misc("fuckadblock.js"),
        "amazon-apstag.js": js_misc("amazon-apstag.js"),
        "scorecardresearch-beacon.js": js_misc("scorecardresearch-beacon.js"),
        "chartbeat.js": js_misc("chartbeat.js"),
    }


# フィルターリストで使われる呼び名 -> Shoji の代替品
_ALIASES = {
    # 空のスクリプト・テキストなど
    "noopjs": "noop.js", "noop.js": "noop.js", "blank-js": "noop.js", "abp-resource:blank-js": "noop.js",
    "nooptext": "noop.txt", "noop.txt": "noop.txt", "blank-text": "noop.txt", "abp-resource:blank-text": "noop.txt",
    "noopcss": "noop.css", "noop.css": "noop.css", "blank-css": "noop.css", "abp-resource:blank-css": "noop.css",
    "noopjson": "noop.json", "noop.json": "noop.json",
    "noopframe": "noop.html", "noop.html": "noop.html", "blank-html": "noop.html",
    "abp-resource:blank-html": "noop.html",
    # 画像
    "1x1.gif": "1x1.gif", "1x1-transparent.gif": "1x1.gif", "1x1-transparent-gif": "1x1.gif",
    "abp-resource:1x1-transparent-gif": "1x1.gif",
    "2x2.png": "2x2.png", "2x2-transparent.png": "2x2.png", "2x2-transparent-png": "2x2.png",
    "abp-resource:2x2-transparent-png": "2x2.png",
    "3x2.png": "3x2.png", "3x2-transparent.png": "3x2.png", "3x2-transparent-png": "3x2.png",
    "abp-resource:3x2-transparent-png": "3x2.png",
    "32x32.png": "32x32.png", "32x32-transparent.png": "32x32.png", "32x32-transparent-png": "32x32.png",
    "abp-resource:32x32-transparent-png": "32x32.png",
    # 音声・動画・動画広告の定義
    "noopmp3-0.1s": "noop-0.1s.mp3", "noop-0.1s.mp3": "noop-0.1s.mp3", "blank-mp3": "noop-0.1s.mp3",
    "abp-resource:blank-mp3": "noop-0.1s.mp3",
    "noopmp4-1s": "noop-1s.mp4", "noop-1s.mp4": "noop-1s.mp4", "blank-mp4": "noop-1s.mp4",
    "abp-resource:blank-mp4": "noop-1s.mp4",
    "noopvast-2.0": "noop-vast2.xml", "noop-vast2.xml": "noop-vast2.xml",
    "noopvast-3.0": "noop-vast3.xml", "noop-vast3.xml": "noop-vast3.xml",
    "noopvast-4.0": "noop-vast4.xml", "noop-vast4.xml": "noop-vast4.xml",
    "noopvmap-1.0": "noop-vmap1.xml", "noop-vmap1.0.xml": "noop-vmap1.xml", "noop-vmap1.xml": "noop-vmap1.xml",
    # 計測・広告ライブラリ
    "google-analytics_analytics.js": "google-analytics.js", "google-analytics.com/analytics.js": "google-analytics.js",
    "google-analytics": "google-analytics.js", "googletagmanager-gtm": "googletagmanager.js",
    "google-analytics_ga.js": "google-analytics-ga.js", "google-analytics.com/ga.js": "google-analytics-ga.js",
    "google-analytics-ga": "google-analytics-ga.js",
    "googletagmanager_gtm.js": "googletagmanager.js", "googletagmanager.com/gtm.js": "googletagmanager.js",
    "googlesyndication_adsbygoogle.js": "googlesyndication-adsbygoogle.js",
    "googlesyndication.com/adsbygoogle.js": "googlesyndication-adsbygoogle.js",
    "googlesyndication-adsbygoogle": "googlesyndication-adsbygoogle.js",
    "googletagservices_gpt.js": "googletagservices-gpt.js", "googletagservices.com/gpt.js": "googletagservices-gpt.js",
    "googletagservices-gpt": "googletagservices-gpt.js",
    "google-ima.js": "google-ima.js", "google-ima3": "google-ima.js",
    "fingerprint2.js": "fingerprint2.js", "fingerprintjs2": "fingerprint2.js",
    "fingerprint3.js": "fingerprint3.js", "fingerprintjs3": "fingerprint3.js",
    "fuckadblock.js-3.2.0": "fuckadblock.js", "fuckadblock.js": "fuckadblock.js", "nofab.js": "fuckadblock.js",
    "prevent-fab-3.2.0": "fuckadblock.js",
    "amazon_apstag.js": "amazon-apstag.js", "amazon-apstag": "amazon-apstag.js",
    "scorecardresearch_beacon.js": "scorecardresearch-beacon.js", "scorecardresearch-beacon": "scorecardresearch-beacon.js",
    "scorecardresearch.com/beacon.js": "scorecardresearch-beacon.js",
    "chartbeat.js": "chartbeat.js",
}

# リストに $redirect が無くても、ブロックしたときに代替品を返すよく使われるスクリプト。
# （EasyList だけを使っている場合でも、これらを呼ぶページが壊れにくくなる）
_BUILTIN = [
    (re.compile(r"^https?://(?:www\.|ssl\.)?google-analytics\.com/(?:analytics|analytics_debug)\.js", re.I),
     "google-analytics.js"),
    (re.compile(r"^https?://(?:www\.|ssl\.)?google-analytics\.com/(?:u/)?ga\.js", re.I), "google-analytics-ga.js"),
    (re.compile(r"^https?://(?:www\.)?googletagmanager\.com/(?:gtm\.js|gtag/js)", re.I), "googletagmanager.js"),
    (re.compile(r"^https?://pagead2\.googlesyndication\.com/pagead/js/adsbygoogle\.js", re.I),
     "googlesyndication-adsbygoogle.js"),
    (re.compile(r"^https?://(?:securepubads\.g\.doubleclick\.net|(?:www\.)?googletagservices\.com)/tag/js/gpt\.js",
                re.I), "googletagservices-gpt.js"),
    (re.compile(r"^https?://imasdk\.googleapis\.com/js/sdkloader/ima3\.js", re.I), "google-ima.js"),
    (re.compile(r"^https?://c\.amazon-adsystem\.com/aax2/apstag\.js", re.I), "amazon-apstag.js"),
]


def canonical(name: str) -> Optional[str]:
    """リストでの呼び名を Shoji の代替品の名前にする（知らない名前は None）"""
    return _ALIASES.get((name or "").strip().lower())


def builtin_for(url: str, rtype: str) -> Optional[str]:
    """よく使われる広告・計測スクリプトなら、その代替品の名前"""
    if rtype not in ("script", "other"):
        return None
    for rx, name in _BUILTIN:
        if rx.match(url):
            return name
    return None


def get(name: str) -> Optional[tuple[str, bytes]]:
    """(Content-Type, 中身)。知らない名前は None"""
    key = canonical(name) or (name if name in _resources() else None)
    if not key:
        return None
    return _resources().get(key)


def known_names() -> set[str]:
    return set(_ALIASES)
