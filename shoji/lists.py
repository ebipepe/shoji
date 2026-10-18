# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""フィルタリストのダウンロード・更新・読み込み。"""
from __future__ import annotations

import re
import threading
import time
import urllib.request
from pathlib import Path

from .config import DATA_DIR, LISTS_DIR, RULES_DIR
from .context import AppContext

BUILTIN = [("builtin_ads.txt", "ad"), ("builtin_trackers.txt", "tracker")]
# ユーザールールは書き込み可能な data 側に置く（exe 版ではインストール先が読み取り専用のため）。
# 初回は rules/user_rules.txt（説明付きのひな形、または以前のバージョンで書いたルール）をコピーする。
USER_RULES = DATA_DIR / "user_rules.txt"
_USER_RULES_TEMPLATE = RULES_DIR / "user_rules.txt"


def ensure_user_rules() -> None:
    if not USER_RULES.exists() and _USER_RULES_TEMPLATE.exists():
        USER_RULES.parent.mkdir(parents=True, exist_ok=True)
        USER_RULES.write_text(_USER_RULES_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")


def _slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower() + ".txt"


def list_file(entry: dict) -> Path:
    return LISTS_DIR / _slug(entry["name"])


def list_status(ctx: AppContext) -> list[dict]:
    out = []
    for e in ctx.cfg["filter_lists"]:
        p = list_file(e)
        st = p.stat() if p.exists() else None
        out.append({**e, "file": p.name, "downloaded": bool(st),
                    "updated": st.st_mtime if st else None, "size": st.st_size if st else 0})
    return out


def load_engine(ctx: AppContext) -> dict:
    sources = []
    for name, cat in BUILTIN:
        p = RULES_DIR / name
        if p.exists():
            sources.append((name, p.read_text(encoding="utf-8"), cat))
    for e in ctx.cfg["filter_lists"]:
        p = list_file(e)
        if e.get("enabled", True) and p.exists():
            sources.append((e["name"], p.read_text(encoding="utf-8", errors="replace"), e.get("category", "ad")))
    ensure_user_rules()
    if USER_RULES.exists():
        # "! category: tracker" 以降の行はトラッカー扱い
        cat, buf, chunks = "ad", [], []
        for line in USER_RULES.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^!\s*category:\s*(ad|tracker)", line.strip(), re.I)
            if m:
                chunks.append(("user", "\n".join(buf), cat))
                cat, buf = m.group(1).lower(), []
            else:
                buf.append(line)
        chunks.append(("user", "\n".join(buf), cat))
        sources.extend(chunks)
    t0 = time.time()
    ctx.engine.load(sources)
    ctx.rules_reloaded()
    summary = ctx.engine.summary()
    summary["load_seconds"] = round(time.time() - t0, 2)
    summary["lists"] = len(sources)
    ctx.status["lists"] = summary
    print(f"[lists] ルール読込: DNS {summary['dns_domains']:,} ドメイン / ネットワーク "
          f"{summary['network_rules']:,} / 要素非表示 {summary['cosmetic_generic'] + summary['cosmetic_specific']:,}"
          f" ({summary['load_seconds']}秒)")
    return summary


def download(entry: dict, timeout: int = 60) -> bool:
    p = list_file(entry)
    p.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(entry["url"], headers={"User-Agent": "Shoji/0.1"})
    try:
        # 自分自身（システムプロキシ）を経由しないよう直接接続する
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            data = r.read()
    except Exception as e:  # noqa: BLE001
        print(f"[lists] {entry['name']} のダウンロードに失敗: {e}")
        return False
    text = data.decode("utf-8", errors="replace")
    if len(text) < 100:
        return False
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    print(f"[lists] {entry['name']} を更新 ({len(data) // 1024:,} KB)")
    return True


def update_lists(ctx: AppContext, force: bool = False) -> int:
    hours = ctx.cfg.get("update_interval_hours", 24)
    updated = 0
    for e in ctx.cfg["filter_lists"]:
        if not e.get("enabled", True):
            continue
        p = list_file(e)
        stale = not p.exists() or (time.time() - p.stat().st_mtime) > hours * 3600
        if force or stale:
            if download(e):
                updated += 1
    if updated:
        load_engine(ctx)
    return updated


def start_updater(ctx: AppContext) -> threading.Thread:
    def loop():
        while True:
            try:
                update_lists(ctx)
            except Exception as e:  # noqa: BLE001
                print(f"[lists] 更新エラー: {e}")
            time.sleep(3600)
    t = threading.Thread(target=loop, name="list-updater", daemon=True)
    t.start()
    return t
