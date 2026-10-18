# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""スクリプトレットを実際のブラウザ（Chromium）で動かして確かめる。Playwright が無ければ飛ばす。

    python tests/test_scriptlets_browser.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shoji import scriptlets  # noqa: E402

CALLS = [
    ("set-constant", ("ads.enabled", "false")),
    ("set-constant", ("cfg.flags.showAds", "noopFunc")),
    ("set-constant", ("navigator.getBattery", "noopPromiseResolve")),
    ("abort-on-property-read", ("adblockDetector",)),
    ("abort-on-property-write", ("popunder",)),
    ("abort-current-script", ("document.title", "badscript")),
    ("addEventListener-defuser", ("load", "adwatch")),
    ("no-setTimeout-if", ("adcheck", "")),
    ("no-window-open-if", ("ads.example",)),
    ("json-prune", ("ad adPlacements", "")),
    ("json-prune", ("items.[-].isAd", "")),
    ("addEventListener-defuser", ("click", "", "elements", ".aeld-only")),
    ("no-fetch-if", ("ads.example", "emptyObj")),
    ("no-xhr-if", ("tracker.example",)),
    ("remove-node-text", ("script", "removeMe")),
    ("remove-attr", ("onclick", "a.ra")),
    ("remove-class", ("blur", ".rc")),
    ("href-sanitizer", ("a.hs", "?url")),
    ("set-local-storage-item", ("consent", "true")),
    ("noeval-if", ("evil",)),
]

PAGE_JS = r"""
const R = window.R = {};
window.ads = { enabled: true };
R.setConstant = window.ads.enabled;
window.cfg = {}; window.cfg.flags = { showAds: 1 };
R.nested = typeof window.cfg.flags.showAds;
R.battery = navigator.getBattery() instanceof Promise;
try { R.aopr = window.adblockDetector; R.aopr = 'not thrown'; } catch (e) { R.aopr = 'thrown'; }
try { window.popunder = 1; R.aopw = 'not thrown'; } catch (e) { R.aopw = 'thrown'; }
R.listener = 0;
window.addEventListener('load', function adwatch() { R.listener += 100; });
window.addEventListener('load', function ok() { R.listener += 1; });
R.timer = 0;
setTimeout(function adcheck() { R.timer += 100; }, 0);
setTimeout(function fine() { R.timer += 1; }, 0);
const w = window.open('https://ads.example/pop');
R.openBlocked = !!w && w.closed === false;
R.prune = JSON.parse('{"ad":1,"adPlacements":[1],"video":2}');
R.arr = JSON.parse('{"items":[{"isAd":1},{"v":1},{"isAd":0,"x":1}]}').items.length;
R.clicks = 0;
document.documentElement.addEventListener('click', () => { R.clicks += 1; });
R.evalBlocked = eval('"evil"') === undefined && eval('1+1') === 2;
try { localStorage.removeItem('x'); } catch (e) {}
R.storage = (function () { try { return localStorage.getItem('consent'); } catch (e) { return 'n/a'; } })();
"""


def run() -> dict:
    from playwright.sync_api import sync_playwright

    js = scriptlets.build(CALLS)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><script>{js}</script></head><body>
<script>{PAGE_JS}</script>
<script id="bad">/* badscript */ try {{ document.title; window.R.acs = 'ran'; }} catch (e) {{ window.R.acs = 'aborted'; }}</script>
<script>try {{ document.title; window.R.acsOther = 'ran'; }} catch (e) {{ window.R.acsOther = 'aborted'; }}</script>
<script>/* removeMe */ window.R.rmnt = 'executed';</script>
<a class="ra" onclick="x()">a</a><div class="rc blur">b</div>
<a class="hs" href="https://go.example/out?url=https%3A%2F%2Freal.example%2Fpage">c</a>
</body></html>"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def route(r):
            if r.request.url.startswith("https://shoji.test/"):
                r.fulfill(status=200, content_type="text/html", body=html)
            else:
                r.fulfill(status=200, body="REAL")
        page.route("**/*", route)
        page.goto("https://shoji.test/")
        page.wait_for_load_state("load")
        page.evaluate("""async () => {
            const r = await fetch('https://ads.example/x'); window.R.fetch = await r.text();
            const r2 = await fetch('https://ok.example/x'); window.R.fetchOk = await r2.text();
            window.R.xhr = await new Promise(res => { const x = new XMLHttpRequest();
                x.open('GET', 'https://tracker.example/t'); x.onload = () => res('fake:' + x.status + ':' + x.responseText);
                x.send(); });
        }""")
        page.evaluate("document.documentElement.click()")
        page.wait_for_timeout(300)
        r = page.evaluate("window.R")
        r["ra"] = page.evaluate("document.querySelector('a.ra').hasAttribute('onclick')")
        r["rc"] = page.evaluate("document.querySelector('.rc').classList.contains('blur')")
        r["hs"] = page.evaluate("document.querySelector('a.hs').getAttribute('href')")
        r["errors"] = errors
        browser.close()
    return r


def test_scriptlets_in_browser():
    import importlib.util
    if importlib.util.find_spec("playwright") is None:
        print("skip: playwright not installed")
        return
    r = run()
    expect = {
        "setConstant": False, "nested": "function", "battery": True, "aopr": "thrown", "aopw": "thrown",
        "listener": 1, "timer": 1, "openBlocked": True, "prune": {"video": 2}, "arr": 1, "clicks": 1, "evalBlocked": True,
        "storage": "true", "acs": "aborted", "acsOther": "ran", "rmnt": None,
        "fetch": "{}", "fetchOk": "REAL", "xhr": "fake:200:", "ra": False, "rc": False,
        "hs": "https://real.example/page",
    }
    bad = {k: (r.get(k), v) for k, v in expect.items() if r.get(k) != v}
    assert not bad, json.dumps(bad, ensure_ascii=False) + " errors=" + json.dumps(r.get("errors"))


if __name__ == "__main__":
    test_scriptlets_in_browser()
    print("OK test_scriptlets_in_browser")
