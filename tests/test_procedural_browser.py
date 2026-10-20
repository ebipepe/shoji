# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""拡張 CSS（手続き型の要素非表示）と $redirect の代替品を、実際のブラウザ（Chromium）で確かめる。
Playwright が無ければ飛ばす。

    python tests/test_procedural_browser.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shoji import injector, procedural, redirects  # noqa: E402
from shoji.config import ASSETS_DIR  # noqa: E402

RULES = [
    "div.card:has-text(スポンサー)",
    "span.label:has-text(/^PR$/):upward(2)",
    "li:has(> a:has-text(広告))",
    ":xpath(//section[@id='x']/div[2])",
    ".rm:has-text(remove me):remove()",
    "body:style(overflow: auto !important)",
    ".fixed:matches-css(position: fixed)",
    "ul.feed > li:not(:has-text(news))",
    "p.short:min-text-length(20)",
    "div:matches-attr(/^data-ad-/)",
    ".anchor:has-text(next) + .sib",
    ":matches-path(/nowhere) .never",
    ".late:has-text(後から)",
    "p.mark:upward(.wrap)",
    ".rc:remove-class(/^blur/)",
    "div[-ext-has='.inner-ad']",
]

HTML = """<!doctype html><html><head><meta charset="utf-8"></head>
<body style="overflow:hidden">
<div class="card" id="c1">スポンサー リンク</div><div class="card" id="c2">ふつうの記事</div>
<div id="g1"><div><span class="label">PR</span></div></div>
<ul><li id="l1"><a>広告です</a></li><li id="l2"><a>記事</a></li></ul>
<section id="x"><div id="x1"></div><div id="x2"></div></section>
<div class="rm" id="rm1">remove me</div>
<div class="fixed" id="f1" style="position:fixed">fixed</div><div class="fixed" id="f2">static</div>
<ul class="feed"><li id="n1">news item</li><li id="n2">promo</li></ul>
<p class="short" id="s1">短い</p><p class="short" id="s2">これはとても長い文章で二十文字を超えています。確実に。</p>
<div id="a1" data-ad-slot="1"></div><div id="a2" data-x="1"></div>
<div class="anchor">next</div><div class="sib" id="sib1"></div>
<div class="never" id="nv"></div>
<div class="wrap" id="w1"><div><p class="mark">m</p></div></div>
<div class="rc blurred keep" id="rc1"></div>
<div id="e1"><div class="inner-ad"></div></div><div id="e2"></div>
</body></html>"""

CHECK_JS = r"""() => {
  const hidden = id => { const e = document.getElementById(id); return !!e && getComputedStyle(e).display === 'none'; };
  return {
    c1: hidden('c1'), c2: hidden('c2'), g1: hidden('g1'), l1: hidden('l1'), l2: hidden('l2'),
    x1: hidden('x1'), x2: hidden('x2'), rm1: document.getElementById('rm1') === null,
    body: getComputedStyle(document.body).overflow, f1: hidden('f1'), f2: hidden('f2'),
    n1: hidden('n1'), n2: hidden('n2'), s1: hidden('s1'), s2: hidden('s2'), a1: hidden('a1'), a2: hidden('a2'),
    sib1: hidden('sib1'), nv: hidden('nv'), late: hidden('late1'), w1: hidden('w1'),
    rc1: document.getElementById('rc1').className, e1: hidden('e1'), e2: hidden('e2')
  };
}"""

EXPECT = {"c1": True, "c2": False, "g1": True, "l1": True, "l2": False, "x1": False, "x2": True, "rm1": True,
          "body": "auto", "f1": True, "f2": False, "n1": False, "n2": True, "s1": False, "s2": True,
          "a1": True, "a2": False, "sib1": True, "nv": False, "late": True, "w1": True, "rc1": "rc keep",
          "e1": True, "e2": False}

SURROGATE_JS = r"""async () => {
  const R = {};
  const wait = ms => new Promise(r => setTimeout(r, ms));
  // Google Analytics
  R.ga = await new Promise(res => { ga('send', 'event', { hitCallback: () => res('called') }); setTimeout(() => res('timeout'), 500); });
  // GPT
  R.gpt = 0;
  googletag.cmd.push(() => { R.gpt += 1; });
  const slot = googletag.defineSlot('/1/a', [300, 250], 'ad1').addService(googletag.pubads()).setTargeting('k', 'v');
  let ended = null;
  googletag.pubads().addEventListener('slotRenderEnded', e => { ended = e.isEmpty; });
  googletag.enableServices(); googletag.display('ad1');
  await wait(50);
  R.gptEmpty = ended; R.gptTarget = slot.getTargeting('k')[0];
  // IMA
  R.ima = await new Promise(res => {
    const loader = new google.ima.AdsLoader(new google.ima.AdDisplayContainer(document.body));
    loader.addEventListener(google.ima.AdErrorEvent.Type.AD_ERROR, e => res(e.getError().getErrorCode()));
    loader.requestAds(new google.ima.AdsRequest());
    setTimeout(() => res('timeout'), 500);
  });
  // AdSense
  (window.adsbygoogle = window.adsbygoogle || []).push({});
  R.ads = document.querySelector('ins.adsbygoogle').getAttribute('data-adsbygoogle-status');
  // GTM
  R.gtm = await new Promise(res => { dataLayer.push({ event: 'x', eventCallback: () => res('called') }); setTimeout(() => res('timeout'), 500); });
  return R;
}"""


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright が無い")
        return 0
    tasks = [procedural.parse(r) for r in RULES]
    css = [c for c in (procedural.plain_css_rule(t) for t in tasks) if c]
    tasks = [t for t in tasks if not procedural.plain_css_rule(t)]
    js = (ASSETS_DIR / "procedural.js").read_text(encoding="utf-8").replace(
        "window.__SHOJI_CFG__", json.dumps({"magic": injector.MAGIC_ORIGIN, "proc": tasks}, ensure_ascii=False))
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.route("https://shoji.blocker/**", lambda route: route.fulfill(status=204, body=""))
        page.set_content(HTML)
        if css:
            page.add_style_tag(content="\n".join(css))
        page.add_script_tag(content=js)
        page.evaluate("""() => setTimeout(() => {
            const d = document.createElement('div'); d.id = 'late1'; d.className = 'late'; d.textContent = '後から追加';
            document.body.appendChild(d); }, 100)""")
        page.wait_for_timeout(600)
        got = page.evaluate(CHECK_JS)
        for k, v in EXPECT.items():
            ok = got.get(k) == v
            failures += not ok
            print(("OK  " if ok else "NG  ") + f"{k}: {got.get(k)!r} (期待 {v!r})")

        # 代替品
        page2 = browser.new_page()
        page2.set_content('<!doctype html><html><body><ins class="adsbygoogle"></ins></body></html>')
        page2.evaluate("window.dataLayer = [];")
        for name in ("google-analytics_analytics.js", "googletagservices_gpt.js", "google-ima.js",
                     "googlesyndication_adsbygoogle.js", "googletagmanager_gtm.js", "noopjs",
                     "fuckadblock.js-3.2.0", "fingerprint2.js", "amazon_apstag.js"):
            ctype, body = redirects.get(name)
            assert ctype.startswith("application/javascript"), name
            page2.add_script_tag(content=body.decode("utf-8"))
        r = page2.evaluate(SURROGATE_JS)
        expect2 = {"ga": "called", "gpt": 1, "gptEmpty": True, "gptTarget": "v", "ima": 1009, "ads": "done", "gtm": "called"}
        for k, v in expect2.items():
            ok = r.get(k) == v
            failures += not ok
            print(("OK  " if ok else "NG  ") + f"surrogate {k}: {r.get(k)!r} (期待 {v!r})")
        browser.close()
    print("失敗", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
