# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""ソース版で、入っている部品が古いままになっていないかを確かめる。

exe 版は requirements-lock.txt の版どおりに作るので、確かめる必要はない。
ソース版は `git pull` しても、install.bat を実行し直さない限り .venv の部品は古いまま残る
（v0.5.3 の Brotli の修正が入らなかった例がある）。そこで起動時に、入っている部品の版を
requirements-lock.txt の版と比べ、古いものがあればログとダッシュボードで知らせる。
新しい版が入っているのは問題にしない（requirements.txt は下限だけの指定なので）。
"""
from __future__ import annotations

import platform
import re
import sys
from importlib import metadata
from pathlib import Path

from .config import BASE_DIR, FROZEN

LOCK_PATH = BASE_DIR / "requirements-lock.txt"


def _version_key(v: str) -> tuple[int, ...] | None:
    """"1.2.1" → (1, 2, 1)。数字以外を含む部分（rc など）があれば比べない"""
    parts = []
    for p in re.split(r"[.]", v.split("+", 1)[0]):
        if not p.isdigit():
            return None
        parts.append(int(p))
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _marker_applies(marker: str) -> bool:
    """ロックファイルの環境マーカーのうち、使われている形だけを評価する（分からなければ対象にする）"""
    env = {
        "sys_platform": sys.platform,
        "os_name": "nt" if sys.platform == "win32" else "posix",
        "platform_python_implementation": platform.python_implementation(),
        "implementation_name": sys.implementation.name,
        "python_version": "%d.%d" % sys.version_info[:2],
        "python_full_version": platform.python_version(),
    }

    def one(m: re.Match) -> str:
        name, op, val = m.group(1), m.group(2), m.group(3)
        cur = env.get(name)
        if cur is None:
            return "True"
        if name.startswith("python"):
            a, b = _version_key(cur), _version_key(val)
            if a is None or b is None:
                return "True"
            res = {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}.get(op, True)
        else:
            res = (cur == val) if op == "==" else (cur != val) if op == "!=" else True
        return str(res)

    expr = re.sub(r"(\w+)\s*(<=|>=|==|!=|<|>)\s*'([^']*)'", one, marker)
    tokens = re.findall(r"\(|\)|[A-Za-z]+|\S", expr)
    if set(tokens) - {"True", "False", "and", "or", "not", "(", ")"}:
        return True
    try:
        value, rest = _parse_or(tokens)
        return value if not rest else True
    except (IndexError, ValueError):
        return True


# True/False・and・or・not・かっこだけの、小さな式の評価（eval は使わない）
def _parse_or(t: list[str]) -> tuple[bool, list[str]]:
    v, t = _parse_and(t)
    while t and t[0] == "or":
        w, t = _parse_and(t[1:])
        v = v or w
    return v, t


def _parse_and(t: list[str]) -> tuple[bool, list[str]]:
    v, t = _parse_not(t)
    while t and t[0] == "and":
        w, t = _parse_not(t[1:])
        v = v and w
    return v, t


def _parse_not(t: list[str]) -> tuple[bool, list[str]]:
    if t[0] == "not":
        v, t = _parse_not(t[1:])
        return not v, t
    if t[0] == "(":
        v, t = _parse_or(t[1:])
        if not t or t[0] != ")":
            raise ValueError("unbalanced")
        return v, t[1:]
    if t[0] in ("True", "False"):
        return t[0] == "True", t[1:]
    raise ValueError(t[0])


def read_lock(text: str) -> list[tuple[str, str, str]]:
    """[(名前, 版, 環境マーカー)]"""
    out = []
    for line in text.splitlines():
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*(?:;\s*([^\\]*?))?\s*\\?\s*$", line)
        if m:
            out.append((m.group(1), m.group(2), (m.group(3) or "").strip()))
    return out


def outdated(lock_text: str, installed=None) -> list[dict]:
    """固定の版より古い部品と、入っていない部品。installed(name) は版の文字列か None を返す"""
    if installed is None:
        def installed(name):
            try:
                return metadata.version(name)
            except metadata.PackageNotFoundError:
                return None
    found = []
    for name, want, marker in read_lock(lock_text):
        if marker and not _marker_applies(marker):
            continue
        have = installed(name)
        if have is None:
            found.append({"name": name, "installed": None, "required": want})
            continue
        a, b = _version_key(have), _version_key(want)
        if a is not None and b is not None and a < b:
            found.append({"name": name, "installed": have, "required": want})
    return found


def check(lock_path: Path = LOCK_PATH) -> list[dict]:
    """ソース版だけ確かめる。ロックファイルが無い・読めないときは何もしない"""
    if FROZEN:
        return []
    try:
        text = lock_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return outdated(text)


def describe(items: list[dict]) -> str:
    return ", ".join(f"{i['name']} {i['installed'] or '-'} → {i['required']}" for i in items)
