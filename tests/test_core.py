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
    html = blocked_page_html("https://evil.example/", "evil.example", "security", "||evil.example^")
    assert "危険なサイト" in html and "window.close" not in html     # 危険サイトの警告は自動で閉じない


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
