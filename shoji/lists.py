# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""フィルタリストのダウンロード・更新・読み込み。"""
from __future__ import annotations

import re
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__, filters
from .config import DATA_DIR, LISTS_DIR, RULES_DIR
from .context import AppContext
from .i18n import t

BUILTIN = [("builtin_ads.txt", "ad"), ("builtin_trackers.txt", "tracker")]
# ユーザールールは書き込み可能な data 側に置く（exe 版ではインストール先が読み取り専用のため）。
# 初回は rules/user_rules.txt（説明付きのひな形、または以前のバージョンで書いたルール）をコピーする。
USER_RULES = DATA_DIR / "user_rules.txt"
_USER_RULES_TEMPLATE = RULES_DIR / "user_rules.txt"


def ensure_user_rules() -> None:
    if not USER_RULES.exists() and _USER_RULES_TEMPLATE.exists():
        USER_RULES.parent.mkdir(parents=True, exist_ok=True)
        USER_RULES.write_text(_USER_RULES_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")


_RULE_LOCK = threading.Lock()
# リストごとの注意（ダウンロードした内容を使わなかった理由など）。ダッシュボードに表示する
WARNINGS: dict[str, str] = {}
# 新しい内容が、前回のこの割合より少なければ使わない（配布元の不具合や乗っ取りへの備え）
SHRINK_LIMIT = 0.5
SHRINK_MIN_RULES = 1000
MAX_LIST_BYTES = 64 * 1024 * 1024


def add_user_rule(rule: str, comment: str = "") -> bool:
    """ユーザールールに 1 行追加する（同じ行が既にあれば何もしない）。追加したら True"""
    with _RULE_LOCK:
        ensure_user_rules()
        text = USER_RULES.read_text(encoding="utf-8") if USER_RULES.exists() else ""
        if rule in (line.strip() for line in text.splitlines()):
            return False
        if text and not text.endswith("\n"):
            text += "\n"
        if comment:
            text += f"! {comment}\n"
        USER_RULES.parent.mkdir(parents=True, exist_ok=True)
        USER_RULES.write_text(text + rule + "\n", encoding="utf-8")
        return True


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
                    "updated": st.st_mtime if st else None, "size": st.st_size if st else 0,
                    "warning": WARNINGS.get(e["name"], "")})
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
            text = p.read_text(encoding="utf-8", errors="replace")
            if e.get("format") == "domains":
                # ドメインの一覧だけのリストからは、ドメイン単位のルールだけを使う
                text, dropped = filters.domains_only(text)
                if dropped:
                    print(t("msg.domains_only", name=e["name"], n=dropped))
            sources.append((e["name"], text, e.get("category", "ad")))
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
    print(t("msg.rules", dns=f"{summary['dns_domains']:,}", net=f"{summary['network_rules']:,}",
            cos=f"{summary['cosmetic_generic'] + summary['cosmetic_specific']:,}", sec=summary["load_seconds"]))
    return summary


def count_rules(text: str) -> int:
    """コメントと空行を除いた行数"""
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith(("!", "[")) and not re.match(r"^#(?:\s|$)", s):
            n += 1
    return n


def check_content(text: str, previous: str | None, force: bool = False) -> str:
    """ダウンロードした内容を使ってよいか。問題があれば理由の鍵（i18n）を返す"""
    head = text[:1024].lstrip().lower()
    if head.startswith(("<!doctype", "<html", "<?xml", "<head", "<body")):
        return "list.warn.html"
    n = count_rules(text)
    if n == 0:
        return "list.warn.empty"
    if previous is not None and not force:
        prev = count_rules(previous)
        if prev >= SHRINK_MIN_RULES and n < prev * SHRINK_LIMIT:
            return "list.warn.shrunk"
    return ""


def download(entry: dict, timeout: int = 60, force: bool = False) -> bool:
    """リストをダウンロードする。失敗したら予備の配布元（mirrors）を順に試す"""
    p = list_file(entry)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 自分自身（システムプロキシ）を経由しないよう直接接続する
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    previous = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
    text, errors, rejected = None, [], ""
    for url in [entry["url"]] + list(entry.get("mirrors") or []):
        req = urllib.request.Request(url, headers={"User-Agent": "Shoji/" + __version__})
        try:
            with opener.open(req, timeout=timeout) as r:
                data = r.read(MAX_LIST_BYTES + 1)
            if len(data) > MAX_LIST_BYTES:
                rejected = "list.warn.large"
                continue
            if len(data) < 100:
                continue
            candidate = data.decode("utf-8", errors="replace")
            problem = check_content(candidate, previous, force)
            if problem:
                rejected = problem
                errors.append(f"{url.split('/')[2]}: {t(problem)}")
                continue
            text = candidate
            break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url.split('/')[2]}: {e}")
    if text is None:
        if rejected:
            # 前回の内容を使い続ける。次の確認は通常どおり（約 1 時間後）
            WARNINGS[entry["name"]] = rejected
            print(t("msg.dl_rejected", name=entry["name"], reason=t(rejected)))
        else:
            print(t("msg.dl_fail", name=entry["name"], err=" / ".join(errors)))
        return False
    WARNINGS.pop(entry["name"], None)
    data = text.encode("utf-8")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    print(t("msg.dl_ok", name=entry["name"], kb=f"{len(data) // 1024:,}"))
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
            if download(e, force=force):
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
                print(t("msg.update_err", err=e))
            time.sleep(3600)
    t = threading.Thread(target=loop, name="list-updater", daemon=True)
    t.start()
    return t
