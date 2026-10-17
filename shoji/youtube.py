# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""YouTube の動画広告除去。

YouTube はプレイヤー設定 (player API / ytInitialPlayerResponse) の中に広告スケジュール
(adPlacements / playerAds / adSlots) を埋め込んでいる。これを通信の段階で取り除くと、
プレイヤーは広告が無いものとして本編を再生する（uBlock Origin の json-prune と同じ方式）。
フィード・関連動画・検索結果に混ざる広告カードも同様に削除する。
"""
from __future__ import annotations

import json
import re
from typing import Any

# プレイヤー応答から削除するキー
PLAYER_AD_KEYS = {"adPlacements", "playerAds", "adSlots", "adBreakHeartbeatParams",
                  "adParams", "adBreakParams", "adInferredBlockingStatus"}
# フィード等で丸ごと削除する広告レンダラー
AD_RENDERERS = {
    "adSlotRenderer", "promotedSparklesWebRenderer", "promotedSparklesTextSearchRenderer",
    "promotedVideoRenderer", "compactPromotedVideoRenderer", "displayAdRenderer",
    "inFeedAdLayoutRenderer", "bannerPromoRenderer", "statementBannerRenderer",
    "searchPyvRenderer", "adActionInterstitialRenderer", "brandVideoShelfRenderer",
    "brandVideoSingletonRenderer", "movingThumbnailAdRenderer", "playerLegacyDesktopWatchAdsRenderer",
    "companionSlotRenderer", "actionCompanionAdRenderer", "linearAdSequenceRenderer",
    "instreamVideoAdRenderer", "adPlacementRenderer", "merchandiseShelfRenderer",
    "primetimePromoRenderer", "mealbarPromoRenderer",
}

YT_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtubekids.com")
API_PATHS = ("/youtubei/v1/player", "/youtubei/v1/next", "/youtubei/v1/browse",
             "/youtubei/v1/search", "/youtubei/v1/reel", "/youtubei/v1/guide",
             "/youtubei/v1/get_watch", "/youtubei/v1/music/")


def is_youtube_host(host: str) -> bool:
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in YT_HOSTS)


def is_youtube_api(host: str, path: str) -> bool:
    return is_youtube_host(host) and path.startswith(API_PATHS)


def _is_ad_item(obj: Any) -> bool:
    if not isinstance(obj, dict) or len(obj) != 1:
        return False
    for k, v in obj.items():
        if k in AD_RENDERERS:
            return True
        # richItemRenderer / richSectionRenderer の中身が広告
        if k in ("richItemRenderer", "richSectionRenderer", "itemSectionRenderer") and isinstance(v, dict):
            content = v.get("content") or {}
            if isinstance(content, dict) and any(c in AD_RENDERERS for c in content):
                return True
            contents = v.get("contents")
            if isinstance(contents, list) and contents and all(_is_ad_item(c) for c in contents):
                return True
    return False


_PLAYER_MARKERS = ("videoDetails", "playabilityStatus", "streamingData")


def _is_player_response(d: dict) -> bool:
    return any(k in d for k in _PLAYER_MARKERS)


def prune(obj: Any) -> int:
    """JSON オブジェクトから広告を取り除き、除去した件数を返す（その場で変更）。
    ・プレイヤー応答（videoDetails 等を持つ dict）からだけ広告スケジュールのキーを削除する
    ・フィード等では、広告レンダラーだけでできた「リストの要素」を丸ごと取り除く
    それ以外の構造には一切手を付けない（YouTube のアプリ本体を壊さないため）。"""
    removed = 0
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if _is_player_response(cur):
                for k in PLAYER_AD_KEYS:
                    if k in cur:
                        v = cur.pop(k)
                        removed += len(v) if isinstance(v, list) and v else 1
            stack.extend(cur.values())
        elif isinstance(cur, list):
            keep = []
            for item in cur:
                if _is_ad_item(item):
                    removed += 1
                else:
                    keep.append(item)
                    stack.append(item)
            if len(keep) != len(cur):
                cur[:] = keep
    return removed


def prune_json_bytes(data: bytes) -> tuple[bytes, int]:
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return data, 0
    n = prune(obj)
    if not n:
        return data, 0
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), n


# HTML 埋め込み (ytInitialPlayerResponse / ytInitialData) はキー名を無害な名前に変えて無効化する。
# プレイヤー応答にしか現れないキーだけを書き換える（他のデータ構造に影響させない）
_HTML_KEY_RE = re.compile(r'"(adPlacements|playerAds|adBreakHeartbeatParams)"\s*:')
_INITIAL_DATA_RE = re.compile(
    r"(var\s+ytInitialData\s*=\s*|window\[\"ytInitialData\"\]\s*=\s*)(\{.*?\});\s*(?=</script>|var |window)", re.S)


def prune_html(html: str) -> tuple[str, int]:
    count = 0

    def _ren(m):
        nonlocal count
        count += 1
        return '"shoji_' + m.group(1) + '":'
    html = _HTML_KEY_RE.sub(_ren, html)

    def _data(m):
        nonlocal count
        try:
            obj = json.loads(m.group(2))
        except ValueError:
            return m.group(0)
        n = prune(obj)
        if not n:
            return m.group(0)
        count += n
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        body = body.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        return m.group(1) + body + ";"
    html = _INITIAL_DATA_RE.sub(_data, html, count=1)
    return html, count
