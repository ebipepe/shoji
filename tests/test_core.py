# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""基本動作のテスト:  python -m pytest tests  （または python tests/test_core.py）"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shoji import injector, youtube  # noqa: E402
from shoji.filters import FilterEngine, literal_piece, NetRule  # noqa: E402
from shoji.privacy import amp_canonical, amp_redirect_url, strip_tracking_params  # noqa: E402

RULES = """
||ads.example.com^
/banner/*$image,third-party
@@||ads.example.com/allowed.js
||cdn.example.org/ad.js$domain=news.example.jp
example.jp##.sidebar-ad
##.adsbygoogle
example.jp#@#.adsbygoogle
@@||safe.example^$document
/^https?:\\/\\/[a-z]+\\.example\\.com\\/track\\d+/
||example.com^$removeparam=ref_id
"""


def engine():
    e = FilterEngine()
    e.load([("t", RULES, "ad"), ("t2", "||tracker.example.net^", "tracker")])
    return e


def test_network():
    e = engine()
    assert e.match_url("https://ads.example.com/x.js", "ads.example.com", "site.jp", "script")
    assert not e.match_url("https://ads.example.com/allowed.js", "ads.example.com", "site.jp", "script")
    assert e.match_url("https://img.site/banner/a.png", "img.site", "other.jp", "image")
    assert not e.match_url("https://img.site/banner/a.png", "img.site", "img.site", "image")
    assert e.match_url("https://cdn.example.org/ad.js", "cdn.example.org", "news.example.jp", "script")
    assert not e.match_url("https://cdn.example.org/ad.js", "cdn.example.org", "other.jp", "script")
    assert e.match_url("https://abc.example.com/track42", "abc.example.com", "x.jp", "xmlhttprequest")
    assert e.categorize("tracker.example.net") == "tracker"


def test_dns():
    e = engine()
    assert e.dns_lookup("ads.example.com") == "ad"
    assert e.dns_lookup("sub.ads.example.com") == "ad"
    assert e.dns_lookup("tracker.example.net") == "tracker"
    assert e.dns_lookup("example.com") is None


def test_cosmetic_and_flags():
    e = engine()
    assert ".sidebar-ad" in e.specific_selectors("www.example.jp")
    assert ".adsbygoogle" in e.generic_exceptions("example.jp")
    assert "adsbygoogle" in e.generic_css()
    assert "document" in e.page_flags("https://safe.example/", "safe.example")


def test_literal_piece():
    r = NetRule(raw="x", pattern=r"^https?:\/\/[a-z]+\.example\.com\/ads?\/", is_regex=True)
    assert literal_piece(r) == ".example.com/ad"


def test_params():
    u, removed = strip_tracking_params("https://shop.jp/item?id=5&utm_source=tw&fbclid=abc&gclid=1")
    assert u == "https://shop.jp/item?id=5" and set(removed) == {"utm_source", "fbclid", "gclid"}
    u, _ = strip_tracking_params("https://www.youtube.com/watch?v=abc&si=xyz")
    assert u == "https://www.youtube.com/watch?v=abc"
    u, _ = strip_tracking_params("https://www.google.com/search?q=a&ei=1&ved=2")
    assert "ei=1" in u


def test_amp():
    assert amp_redirect_url("https://www.google.com/amp/s/news.example.jp/a/amp") == "https://news.example.jp/a/amp"
    assert amp_redirect_url("https://news-example-jp.cdn.ampproject.org/c/s/news.example.jp/a") == "https://news.example.jp/a"
    html = '<html amp lang="ja"><head><link rel="canonical" href="https://news.example.jp/a"></head>'
    assert amp_canonical(html, "https://news.example.jp/a/amp") == "https://news.example.jp/a"
    assert amp_canonical("<html><head></head>", "https://x/") is None


def test_youtube():
    player = {"videoDetails": {"videoId": "x"}, "adPlacements": [{"a": 1}, {"b": 2}],
              "playerAds": [{}], "adSlots": [{}], "streamingData": {"formats": []}}
    data, n = youtube.prune_json_bytes(json.dumps(player).encode())
    obj = json.loads(data)
    assert n >= 3 and "adPlacements" not in obj and "streamingData" in obj
    feed = {"contents": [{"richItemRenderer": {"content": {"adSlotRenderer": {}}}},
                         {"richItemRenderer": {"content": {"videoRenderer": {"videoId": "v"}}}}]}
    youtube.prune(feed)
    assert len(feed["contents"]) == 1
    other = {"adSlots": [1], "contents": []}          # プレイヤー応答以外は触らない
    assert youtube.prune(other) == 0 and "adSlots" in other
    html = 'var ytInitialPlayerResponse = {"adPlacements":[1],"playerAds":[2],"x":1};</script>'
    out, n = youtube.prune_html(html)
    assert '"adPlacements"' not in out and n == 2


def test_inject_and_csp():
    snippet, sh, csh = injector.build_snippet({"f": {}, "s": {}, "magic": "x", "sel": [".a"], "exc": []},
                                              [".広告"], [], [".gen-ad"], True, "1")
    assert snippet.isascii()
    out = injector.inject('<html><head><meta charset="utf-8"><title>t</title></head></html>', snippet)
    assert out.index("<script>") > out.index("charset")
    csp = injector.patch_csp("default-src 'self'; script-src 'self' 'nonce-x'", sh, csh)
    assert sh in csp and "https://shoji.blocker" in csp.split("style-src")[1] and "connect-src" in csp
    # YouTube のようにカンマ区切りで複数ポリシーがある場合、インライン許可済みのポリシーには触らない
    yt = ("script-src 'self' 'unsafe-inline';report-uri https://r/a, "
          "script-src 'nonce-x' 'unsafe-inline' 'strict-dynamic';report-uri https://r/b, require-trusted-types-for 'script'")
    out = injector.patch_csp(yt, sh, csh).split(", ")
    assert len(out) == 3 and sh not in out[0] and sh in out[1] and out[2] == "require-trusted-types-for 'script'"


def test_builtin_https_exclusions():
    from shoji.config import BUILTIN_HTTPS_EXCLUSIONS, DEFAULT_CONFIG, is_whitelisted
    for host in ("www.paypal.com", "secure.chase.com", "s10.kabu.co.jp", "mabanque.bnpparibas", "claude.ai"):
        assert is_whitelisted(host, BUILTIN_HTTPS_EXCLUSIONS), host
    for host in ("www.youtube.com", "example.com", "notpaypal.com"):
        assert not is_whitelisted(host, BUILTIN_HTTPS_EXCLUSIONS), host
    assert DEFAULT_CONFIG["https_exclusions"] == []
    assert len(set(BUILTIN_HTTPS_EXCLUSIONS)) == len(BUILTIN_HTTPS_EXCLUSIONS)


def test_scriptlets():
    from shoji import scriptlets
    from shoji.filters import FilterEngine
    assert scriptlets.parse("+js(aopr.js, foo)") == ("abort-on-property-read", ("foo",))
    assert scriptlets.parse("+js(unknown-thing, 1)") is None
    assert scriptlets.split_args(r"a, b\, c, 'd, e'") == ["a", "b, c", "d, e"]
    e = FilterEngine()
    e.load([("t", "example.com,~sub.example.com##+js(set, ads, false)\n"
                  "example.*##+js(nostif, adb)\n"
                  "example.com#@#+js(nostif, adb)\n"
                  "other.org##+js(nowoif)\nother.org#@#+js()\n", "ad")])
    assert e.scriptlets_for("www.example.com") == [("set-constant", ("ads", "false"))]
    assert e.scriptlets_for("sub.example.com") == []
    assert e.scriptlets_for("example.de") == [("no-setTimeout-if", ("adb",))]
    assert e.scriptlets_for("other.org") == []
    js = scriptlets.build(e.scriptlets_for("www.example.com"))
    assert js.startswith("(function(){") and '"set-constant"' in js and "</" not in js


def test_request_log():
    from shoji.reqlog import RequestLog
    log = RequestLog(maxlen=3)
    for i in range(5):
        log.add("blocked" if i % 2 else "passed", f"https://ex{i}.com/a.js", f"ex{i}.com", rule="||ex.com^")
    items = log.query()
    assert [e["host"] for e in items] == ["ex4.com", "ex3.com", "ex2.com"]
    assert [e["host"] for e in log.query(action="blocked")] == ["ex3.com"]
    assert log.query(since=log.last_id()) == []
    log.enabled = False
    assert log.add("passed", "x") is None


def test_annoyance_lists():
    import json
    import tempfile
    from pathlib import Path
    from shoji.config import Config
    from shoji.filters import FilterEngine
    # 古い設定ファイル（迷惑要素リストが無い）にも新しいリストが加わり、オフのまま
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        p.write_text(json.dumps({"filter_lists": [{"name": "EasyList", "url": "https://easylist.to/easylist/easylist.txt",
                                                   "category": "ad", "enabled": False}]}), encoding="utf-8")
        cfg = Config(p).get()
        fl = {e["name"]: e for e in cfg["filter_lists"]}
        assert fl["EasyList"]["enabled"] is False and "AdGuard Widgets" in fl
        assert fl["AdGuard Widgets"]["enabled"] is False and fl["AdGuard Widgets"]["category"] == "annoyance"
    # 迷惑要素のドメインは DNS では止めず、URL 一致の分類は annoyance
    e = FilterEngine()
    e.load([("w", "||chat-widget.example^\nexample.com##.cookie-bar\n", "annoyance")])
    assert e.dns_lookup("chat-widget.example") is None
    rule = e.match_url("https://chat-widget.example/w.js", "chat-widget.example", "example.com", "script")
    assert rule and e.categorize("chat-widget.example", rule.category) == "annoyance"
    assert e.specific_selectors("example.com") == [".cookie-bar"]


def test_picker_rule_validation():
    import tempfile
    from pathlib import Path
    from unittest import mock
    from mitmproxy import http
    from shoji import lists
    from shoji.config import Config
    from shoji.context import AppContext
    from shoji.filters import FilterEngine
    from shoji.proxy_addon import ShojiAddon
    with tempfile.TemporaryDirectory() as d:
        ctx = AppContext(Config(Path(d) / "c.json"), mock.MagicMock(), FilterEngine())
        addon = ShojiAddon(ctx)
        addon._picker_times = []

        def send(rule, origin="https://www.example.com"):
            req = http.Request.make("POST", "https://shoji.blocker/user-rule", '{"rule": "%s"}' % rule,
                                    {"Origin": origin, "Content-Type": "text/plain"})
            return addon._picker_rule(req)
        with mock.patch.object(lists, "USER_RULES", Path(d) / "user_rules.txt"), \
                mock.patch.object(lists, "load_engine"):
            assert send("example.com##.promo")[0]
            assert not send("other.com##.promo")[0]                   # 他のサイト
            assert not send("example.com#@#.ad")[0]                   # 例外ルール
            assert not send("@@||ads.example^")[0]                    # ネットワーク例外
            assert not send("example.com##+js(nowoif)")[0]            # スクリプトレット
            assert not send("example.com##a{color:red}")[0]           # CSS の注入
            assert "example.com##.promo" in (Path(d) / "user_rules.txt").read_text(encoding="utf-8")


def test_security_lists():
    from shoji.filters import FilterEngine
    from shoji.injector import blocked_page_html
    from shoji.proxy_addon import _should_block
    e = FilterEngine()
    e.load([("ads", "||evil.example^\n||ads.example^\n", "ad"),
            ("mal", "||evil.example^$all\n||phish.example/login^\n||miner.example^$third-party\n", "security")])
    assert e.dns_lookup("www.evil.example") == "security"            # 広告より危険サイトを優先
    assert e.dns_lookup("miner.example") == "security"
    assert e.dns_lookup("ads.example") == "ad"
    rule = e.match_url("https://phish.example/login?x=1", "phish.example", "phish.example", "document")
    assert rule and e.categorize("phish.example", rule.category) == "security"
    F = {"block_ads": False, "block_trackers": False, "block_malware": True}
    assert _should_block("security", F) and not _should_block("ad", F)
    from shoji import i18n
    i18n.configure(lambda: {"app": {"language": "ja"}})
    html = blocked_page_html("https://evil.example/", "evil.example", "security", "||evil.example^")
    assert "危険なサイト" in html and "window.close" not in html     # 危険サイトの警告は自動で閉じない
    i18n.configure(lambda: {"app": {"language": "en"}})
    assert "Dangerous site blocked" in blocked_page_html("https://evil.example/", "evil.example", "security", "r")


def test_i18n():
    import json
    import re
    from shoji import i18n
    for key, entry in i18n.MESSAGES.items():
        assert set(entry) == {"ja", "en"} and all(entry.values()), key
        # 差し込み {name} が両方の言語でそろっている
        assert set(re.findall(r"{(\w+)}", entry["ja"])) == set(re.findall(r"{(\w+)}", entry["en"])), key
    i18n.configure(lambda: {"app": {"language": "en"}})
    assert i18n.lang() == "en" and i18n.t("tray.quit") == "Quit Shoji"
    i18n.configure(lambda: {"app": {"language": "auto"}})
    assert i18n.lang() in ("ja", "en") and i18n.setting() == "auto"
    # ダッシュボードの辞書も、日本語と英語で同じキーを持つ
    src = (Path(__file__).resolve().parent.parent / "shoji" / "assets" / "i18n.js").read_text(encoding="utf-8")
    ja = set(re.findall(r"'([a-z0-9_.]+)':", src.split("\n  en: {")[0]))
    en = set(re.findall(r"'([a-z0-9_.]+)':", src.split("\n  en: {")[1]))
    assert ja == en and len(ja) > 200, (ja ^ en)
    json.dumps(sorted(ja))


def test_tokens_for_allow_pages():
    import tempfile
    from unittest import mock
    from shoji.config import Config
    from shoji.context import AppContext
    from shoji.filters import FilterEngine
    from shoji.injector import allow_site_html, blocked_page_html
    with tempfile.TemporaryDirectory() as d:
        ctx = AppContext(Config(Path(d) / "c.json"), mock.MagicMock(), FilterEngine())
        tok = ctx.issue_token("allow-site", "example.com")
        assert not ctx.use_token(tok, "allow", "example.com")            # 用途が違う
        tok = ctx.issue_token("allow-site", "example.com")
        assert not ctx.use_token(tok, "allow-site", "evil.com")          # サイトが違う
        tok = ctx.issue_token("allow-site", "example.com")
        assert ctx.use_token(tok, "allow-site", "example.com")
        assert not ctx.use_token(tok, "allow-site", "example.com")       # 使い捨て
        assert not ctx.use_token("", "allow", "example.com")
    assert "&amp;t=abc" in blocked_page_html("https://ads.example/", "ads.example", "ad", "r", "abc")
    page = allow_site_html("example.com", "https://example.com/a?b=<x>", "tok123")
    assert 'value="tok123"' in page and "<x>" not in page


def test_shortcuts():
    from shoji.config import DEFAULT_CONFIG, normalize_shortcut
    assert normalize_shortcut("ctrl + shift+alt+h") == "Ctrl+Shift+Alt+H"
    assert normalize_shortcut("Alt+Ctrl+1") == "Ctrl+Alt+1"
    assert normalize_shortcut("F2") == "F2" and normalize_shortcut("") == ""
    for bad in ("h", "Shift+H", "Win+H", "Ctrl+Ctrl+H", "Ctrl+Shift+Alt+Period", "Ctrl+F13"):
        assert normalize_shortcut(bad) is None, bad
    assert DEFAULT_CONFIG["app"]["shortcuts"] == {"picker": "Ctrl+Shift+Alt+H", "site_off": "Ctrl+Shift+Alt+P"}


def test_procedural_parse():
    from shoji import procedural as P
    assert P.parse("div.ad:has-text(広告)") == {"s": "div.ad", "o": [["text", ["広告", ""]]]}
    t = P.parse("li:not(:has-text(news))")
    assert t["o"][0][0] == "not" and t["o"][0][1] == {"s": None, "o": [["text", ["news", ""]]]}
    assert P.parse("a > :has-text(x)")["s"] == "a >*"
    assert P.parse(":xpath(//div)")["s"] is None
    assert P.parse(".x:has-text(a):remove()")["a"] == ["remove"]
    assert P.parse(":matches-path(/a) .ad:upward(2)") == {"s": ".ad", "o": [["up", 2]], "p": ["\\/a", ""]}
    assert P.parse("div[-ext-has='.x']")["s"] == "div:has(.x)"
    # ブラウザの CSS で書けるものは手続き型にしない
    assert not P.is_procedural("div:has(> .a):not(.b)")
    assert P.is_procedural("div:has(.a:has(.b))")
    for bad in ("div:others()", ".a:style(background: url(x))", ".a:remove():has-text(x)", "div:nth-ancestor(a)"):
        try:
            P.parse(bad)
        except P.Unsupported:
            continue
        raise AssertionError(bad)
    assert P.plain_css_rule(P.parse("body:style(overflow: auto !important)")) == "body{overflow:auto!important}"
    sel, task = P.parse_css_injection("#top { remove: true; }")
    assert task == {"s": "#top", "o": [], "a": ["remove"]}


def test_procedural_engine():
    from shoji.filters import FilterEngine
    e = FilterEngine()
    e.load([("t", "\n".join([
        "example.com##div:has-text(PR)",
        "example.com#?#div:-abp-contains(PR)",          # 同じ手順になるので 1 件にまとまる
        "example.com,~sub.example.com##.x:upward(1)",
        "example.com#$#body { overflow: auto !important; }",
        "other.com##p:has-text(a)",
        "other.com#@#p:has-text(a)",
        "##div:has-text(generic)",                        # 全サイト向けは使わない
        "example.com#%#window.x=1",                        # AdGuard の JS ルールは使わない
    ]), "ad")])
    tasks, css = e.procedural_for("www.example.com")
    assert len(tasks) == 2 and css == ["body{overflow:auto!important}"], (tasks, css)
    assert len(e.procedural_for("sub.example.com")[0]) == 1
    assert e.procedural_for("other.com") == ([], [])
    assert e.counts["cosmetic_unsupported"] == 2


def test_redirects():
    from shoji import redirects
    from shoji.filters import FilterEngine
    e = FilterEngine()
    e.load([("t", "\n".join([
        "||ads.example/lib.js$script,redirect=noopjs",
        "||cdn.example/track.js$script,redirect-rule=googletagmanager_gtm.js",
        "||cdn.example^$script,redirect-rule=noopjs:5",
        "@@||ads.example/lib.js$redirect=noopjs,domain=keep.example",
    ]), "ad")])
    u = "https://ads.example/lib.js"
    assert e.match_url(u, "ads.example", "site.example", "script") is not None
    assert e.redirect_for(u, "ads.example", "site.example", "script") == "noopjs"
    # @@...$redirect は代替品を使わないだけで、ブロックは続く
    assert e.match_url(u, "ads.example", "keep.example", "script") is not None
    assert e.redirect_for(u, "ads.example", "keep.example", "script") is None
    # $redirect-rule は単独ではブロックしない。優先度の高い方を使う
    u2 = "https://cdn.example/track.js"
    assert e.match_url(u2, "cdn.example", "site.example", "script") is None
    assert e.redirect_for(u2, "cdn.example", "site.example", "script") == "noopjs"
    for name in ("noopjs", "1x1.gif", "2x2.png", "noopmp3-0.1s", "noopmp4-1s", "google-ima.js",
                 "googletagservices_gpt.js", "abp-resource:blank-js", "noopvast-4.0"):
        assert redirects.get(name), name
    assert redirects.get("click2load.html") is None
    assert redirects.builtin_for("https://www.googletagmanager.com/gtag/js?id=G-1", "script") == "googletagmanager.js"
    assert redirects.builtin_for("https://www.googletagmanager.com/gtag/js?id=G-1", "image") is None
    png = redirects.get("32x32.png")[1]
    assert png.startswith(b"\x89PNG") and png[16:24] == b"\x00\x00\x00\x20\x00\x00\x00\x20"


def test_domains_only_lists():
    from shoji.filters import domains_only
    text = "\n".join([
        "! comment", "# hosts comment", "",
        "||ads.example^", "||track.example^$important", "@@||ok.example^|", "0.0.0.0 bad.example",
        "example.com##.ad", "##+js(set-constant, a, 1)", "/banner/*", "@@||site.example^$document",
        "||cdn.example/path.js", "example.com#$#body { color: red }", "||doubleclick.net^$badfilter",
    ])
    kept, dropped = domains_only(text)
    assert kept.splitlines() == ["||ads.example^", "||track.example^$important", "@@||ok.example^|", "0.0.0.0 bad.example"], kept
    assert dropped == 7, dropped
    from shoji.config import DEFAULT_CONFIG
    fmt = {e["name"]: e.get("format") for e in DEFAULT_CONFIG["filter_lists"]}
    assert fmt["Peter Lowe's list"] == "domains" and fmt["AdGuard DNS filter"] == "domains"
    assert fmt["EasyList"] is None


def test_security_not_lifted_by_list_exceptions():
    from shoji.filters import FilterEngine
    e = FilterEngine()
    e.load([
        ("URLhaus", "||evil.example^\n||mal.example/payload.exe", "security"),
        ("EasyList", "||ads.example^\n@@||evil.example^\n@@||mal.example^$script\n@@||ads.example/ok.js", "ad"),
    ])
    # 広告リストの例外では、危険サイトのブロックは解除されない
    assert e.dns_lookup("evil.example") == "security"
    assert e.match_url("https://evil.example/x", "evil.example", "site.example", "script") is not None
    assert e.match_url("https://mal.example/payload.exe", "mal.example", "site.example", "script") is not None
    # 広告のブロックは、従来どおり例外で解除できる
    assert e.match_url("https://ads.example/ok.js", "ads.example", "site.example", "script") is None
    # 利用者自身のルールなら解除できる
    e2 = FilterEngine()
    e2.load([("URLhaus", "||evil.example^", "security"), ("user", "@@||evil.example^", "ad")])
    assert e2.dns_lookup("evil.example") is None
    assert e2.match_url("https://evil.example/x", "evil.example", "site.example", "script") is None


def test_list_download_checks():
    from shoji import lists
    rules = "\n".join(f"||ad{i}.example^" for i in range(2000))
    assert lists.check_content(rules, None) == ""
    assert lists.check_content("<!DOCTYPE html><html><body>502 Bad Gateway</body></html>" + "x" * 200, None) == "list.warn.html"
    assert lists.check_content("! only comments\n! here", None) == "list.warn.empty"
    small = "\n".join(f"||ad{i}.example^" for i in range(500))
    assert lists.check_content(small, rules) == "list.warn.shrunk"
    assert lists.check_content(small, rules, force=True) == ""          # 「今すぐ更新」では取り込む
    assert lists.check_content(small, small[:100]) == ""                # 前回が小さいリストは対象外
    assert lists.count_rules("! c\n# hosts\n[Adblock Plus 2.0]\n##.ad\n||a^\n") == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
