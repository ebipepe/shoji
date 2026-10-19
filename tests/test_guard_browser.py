# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""詐欺ページ対策（guard.js）を実際のブラウザで確かめる。Playwright が無ければ飛ばす。

    python tests/test_guard_browser.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GUARD = (ROOT / "shoji" / "assets" / "guard.js").read_text(encoding="utf-8")
CFG = json.dumps({"f": {"block_malware": True}, "magic": "https://shoji.blocker"})

SCAM = """<h1>警告: お使いのコンピューターはウイルスに感染しています</h1>
<p>Microsoft Windows Defender がトロイの木馬を検出しました。コンピューターはロックされました。</p>
<p>今すぐサポートセンターにお電話ください: 0120-123-456</p>
<script>for (var i = 0; i < 30; i++) history.pushState({}, '', '#x' + i);
window.addEventListener('beforeunload', function (e) { e.preventDefault(); });
setTimeout(function () { for (var i = 0; i < 8; i++) alert('ウイルスに感染しています'); }, 200);</script>"""
NEWS = """<h1>新型ウイルスの感染者が増加</h1><p>相談窓口（0120-565-653）にお電話ください。マイクロソフトの決算も発表。</p>
<script>setTimeout(function () { alert('確認'); }, 200);</script>"""
QUIZ = """<p>Quiz</p><script>setTimeout(function () { alert('1'); confirm('2'); alert('3'); }, 200);</script>"""


def page(body: str) -> str:
    js = GUARD.replace("window.__SHOJI_CFG__", CFG)
    return f'<!doctype html><html><head><meta charset="utf-8"><script>{js}</script></head><body>{body}</body></html>'


def test_guard_in_browser():
    if importlib.util.find_spec("playwright") is None:
        print("skip: playwright not installed")
        return
    from playwright.sync_api import sync_playwright
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, body in (("scam", SCAM), ("news", NEWS), ("quiz", QUIZ)):
            pg = browser.new_page()
            n = {"dialogs": 0}

            def on_dialog(d, n=n):
                n["dialogs"] += 1
                d.dismiss()
            pg.on("dialog", on_dialog)
            html = page(body)

            def handle(route, _req, html=html):
                if route.request.url.startswith("https://guard.test/"):
                    route.fulfill(status=200, content_type="text/html", body=html)
                else:
                    route.abort()
            pg.route("**/*", handle)
            pg.goto("https://guard.test/")
            pg.wait_for_timeout(2500)
            results[name] = (pg.evaluate("!!document.querySelector('shoji-guard')"), n["dialogs"])
            pg.close()
        browser.close()
    assert results["scam"][0] and results["scam"][1] <= 5, results       # 検出し、ダイアログの連発を止める
    assert results["news"] == (False, 1), results                          # ふつうのニュースは反応しない
    assert results["quiz"] == (False, 3), results                          # 数回のダイアログは止めない


if __name__ == "__main__":
    test_guard_in_browser()
    print("OK test_guard_in_browser")
