# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""スクリプトレット（example.com##+js(name, args…)）の解釈と、ページに埋め込む JavaScript の組み立て。

実際の処理は shoji/assets/scriptlets.js にある（Shoji 独自の実装。uBlock Origin のコードは含まない）。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import ASSETS_DIR

_SECTION = re.compile(r"^//@ (.+)$", re.M)


@lru_cache(maxsize=1)
def library() -> tuple[str, dict[str, str], dict[str, str]]:
    """(共通ヘルパー, {正式名: 関数ソース}, {別名: 正式名})"""
    text = (ASSETS_DIR / "scriptlets.js").read_text(encoding="utf-8")
    parts = _SECTION.split(text)
    helpers, funcs, aliases = "", {}, {}
    # parts = [前置き, 名前行, 本体, 名前行, 本体, …]
    for i in range(1, len(parts) - 1, 2):
        names = parts[i].split()
        body = parts[i + 1].strip()
        if names[0] == "_helpers":
            helpers = body
            continue
        funcs[names[0]] = body
        for n in names:
            aliases[n] = names[0]
    return helpers, funcs, aliases


def canonical(name: str) -> str | None:
    name = name.strip()
    if name.endswith(".js"):
        name = name[:-3]
    return library()[2].get(name)


def split_args(s: str) -> list[str]:
    """uBlock Origin 形式の引数を分割する。カンマ区切り、\\, でカンマ自体、'…' "…" `…` で囲める"""
    args, cur, i, n = [], [], 0, len(s)
    quote = None
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in ",'\"`\\":
            cur.append(s[i + 1])
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
            else:
                cur.append(c)
        elif c in "'\"`" and not "".join(cur).strip():
            cur = []
            quote = c
        elif c == ",":
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    args.append("".join(cur).strip())
    return args


def parse(body: str) -> tuple[str, tuple[str, ...]] | None:
    """'+js(name, a, b)' の中身 → ('正式名', ('a', 'b'))。未対応なら None。空の +js() は ('', ())"""
    if not (body.startswith("+js(") and body.endswith(")")):
        return None
    inner = body[4:-1].strip()
    if not inner:
        return "", ()
    parts = split_args(inner)
    name = canonical(parts[0])
    if not name:
        return None
    return name, tuple(parts[1:])


def key(name: str, args: tuple[str, ...]) -> str:
    return name + "\x00" + "\x00".join(args)


def build(calls: list[tuple[str, tuple[str, ...]]]) -> str:
    """ページに埋め込むスクリプト（必要な関数だけを含める）"""
    if not calls:
        return ""
    helpers, funcs, _ = library()
    used = sorted({n for n, _ in calls if n in funcs})
    if not used:
        return ""
    table = ",".join(f"{json.dumps(n)}:{funcs[n]}" for n in used)
    data = json.dumps([[n, list(a)] for n, a in calls if n in funcs], ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return ("(function(){'use strict';const S=" + helpers + ";const F={" + table + "};"
            "for(const c of " + data + "){try{F[c[0]].apply(null,c[1]);}catch(e){}}})();\n")
