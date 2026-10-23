# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""X（旧 Twitter）の広告ツイート（プロモーション）の除去。

X のページは、タイムラインやツイートの詳細を GraphQL の API（JSON）で受け取って表示する。
広告のツイートは普通のツイートと同じ JSON に混ざって届き、次の印が付いている。

- タイムラインの項目の ID が "promoted-" で始まる（例: promoted-tweet-…）
- 項目の中身（itemContent）に "promotedMetadata" がある

これを通信の段階で取り除くと、画面の言語や見た目（「広告」「Promoted」などの表示）が変わっても消せる。
"""
from __future__ import annotations

import json
from typing import Any

X_HOSTS = ("x.com", "twitter.com")


def is_x_host(host: str) -> bool:
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in X_HOSTS)


def is_x_api(host: str, path: str) -> bool:
    """広告が混ざる JSON を返す API か（GraphQL と、古い形式の /i/api/・/2/ の API）"""
    return is_x_host(host) and ("/graphql/" in path or path.startswith(("/i/api/", "/2/")))


def _item_content(obj: dict) -> Any:
    for path in (("content", "itemContent"), ("item", "itemContent"), ("itemContent",)):
        cur: Any = obj
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if isinstance(cur, dict):
            return cur
    return None


def is_promoted(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    entry_id = obj.get("entryId")
    if isinstance(entry_id, str) and entry_id.startswith(("promoted-", "promotedTweet")):
        return True
    content = _item_content(obj)
    return bool(content and content.get("promotedMetadata"))


def prune(obj: Any) -> int:
    """広告の項目を取り除き、取り除いた数を返す"""
    removed = 0
    if isinstance(obj, list):
        keep = [x for x in obj if not is_promoted(x)]
        removed += len(obj) - len(keep)
        if removed:
            obj[:] = keep
        for x in obj:
            removed += prune(x)
    elif isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, (dict, list)):
                removed += prune(v)
    return removed


def prune_json_bytes(data: bytes) -> tuple[bytes, int]:
    # 広告の印が無ければ、読み込みも書き直しもしない（大半の応答はここで終わる）
    if b"promoted" not in data:
        return data, 0
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return data, 0
    n = prune(obj)
    if not n:
        return data, 0
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), n
