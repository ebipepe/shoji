# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""フィルタエンジン。

Adblock Plus / uBlock Origin / AdGuard 形式のフィルタリストと hosts 形式を読み込み、
  * ネットワークルール (URL ブロック / 例外 / $removeparam)
  * ドメインルール (DNS フィルタリング用)
  * 要素非表示ルール (##selector)
に振り分けて高速に照合できる索引を作る。
"""
from __future__ import annotations

import json
import re
import threading
from functools import lru_cache
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import procedural, scriptlets

# --------------------------------------------------------------------------
# ドメインユーティリティ
# --------------------------------------------------------------------------
# 簡易 Public Suffix（よく使われる 2 階層サフィックス）
_MULTI_SUFFIX = {
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "ad.jp", "ed.jp", "gr.jp", "lg.jp",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz",
    "com.br", "com.cn", "com.tw", "com.hk", "co.kr", "or.kr", "com.sg", "co.in",
    "com.mx", "com.tr", "co.za", "com.ar", "co.id", "com.my", "com.ph", "com.vn",
    "github.io", "blogspot.com", "appspot.com", "cloudfront.net", "herokuapp.com",
    "azurewebsites.net", "netlify.app", "vercel.app", "pages.dev", "workers.dev",
}


@lru_cache(maxsize=65536)
def registrable_domain(host: str) -> str:
    host = (host or "").lower().rstrip(".")
    if not host or re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host):
        return host
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_SUFFIX:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_third_party(req_host: str, page_host: str) -> bool:
    if not page_host:
        return False
    return registrable_domain(req_host) != registrable_domain(page_host)


def cosmetic_keys(host: str) -> list[str]:
    """要素非表示・スクリプトレットを引くキー。ドメインの後ろ側に加え、example.* 形式（全 TLD）も含める"""
    out = []
    for s in host_suffixes(host):
        out.append(s)
        labels = s.split(".")
        if len(labels) >= 2:
            out.append(".".join(labels[:-1]) + ".*")
        if len(labels) >= 3:
            out.append(".".join(labels[:-2]) + ".*")
    return list(dict.fromkeys(out))


def host_suffixes(host: str) -> Iterable[str]:
    """a.b.example.com -> a.b.example.com, b.example.com, example.com, com"""
    host = (host or "").lower().rstrip(".")
    while host:
        yield host
        i = host.find(".")
        if i < 0:
            return
        host = host[i + 1:]


def _domain_opt_match(host: str, dom: str) -> bool:
    """$domain= の 1 要素との一致（example.* のエンティティ形式に対応）"""
    if dom.endswith(".*"):
        base = dom[:-2]
        rd = registrable_domain(host)
        suffix = rd.partition(".")[2]          # 公開サフィックス (例: co.jp)
        stem = host[: len(host) - len(suffix) - 1] if suffix else host
        return stem == base or stem.endswith("." + base)
    return host == dom or host.endswith("." + dom)


# --------------------------------------------------------------------------
# リソース種別
# --------------------------------------------------------------------------
TYPE_ALIASES = {
    "script": "script", "image": "image", "stylesheet": "stylesheet", "css": "stylesheet",
    "object": "object", "xmlhttprequest": "xmlhttprequest", "xhr": "xmlhttprequest",
    "subdocument": "sub_frame", "frame": "sub_frame", "document": "document", "doc": "document",
    "media": "media", "font": "font", "ping": "ping", "beacon": "ping", "websocket": "websocket",
    "other": "other", "popup": "document", "fetch": "xmlhttprequest",
}
# 種別に関係なく無視してよいオプション
_IGNORED_OPTS = {"match-case", "all", "important", "badfilter", "strict1p", "strict3p",
                 "~match-case", "stealth", "~important", "cookie", "network", "content",
                 "extension", "~extension", "jsinject", "urlblock", "elemhide", "ehide",
                 "generichide", "ghide", "specifichide", "shide", "genericblock", "popunder",
                 "inline-script", "inline-font", "empty", "mp4", "1p", "3p", "first-party",
                 "third-party", "~third-party", "~first-party", "~1p", "~3p", "csp", "header",
                 "permissions", "to", "denyallow", "method", "redirect", "redirect-rule",
                 "rewrite", "removeparam", "queryprune", "domain", "from", "app", "sitekey",
                 "replace", "hls", "jsonprune", "xmlprune", "ipaddress", "reason", "uritransform",
                 "urltransform", "removeheader"}
_UNSUPPORTED_OPTS = {"csp", "header", "permissions", "replace", "hls", "jsonprune", "xmlprune",
                     "removeheader", "urltransform", "uritransform", "app", "sitekey", "method",
                     "ipaddress", "to", "denyallow", "cookie", "stealth", "jsinject"}

_PROCEDURAL = re.compile(
    r":-abp-|:has-text|:contains|:xpath|:upward|:remove\(|:style\(|:matches-|:min-text-length|"
    r":watch-attr|:others|:if\(|:if-not|:nth-ancestor|:matches-path|:matches-attr|"
    r":matches-prop|:remove-attr|:remove-class|\[-ext-|:shadow")


@dataclass(eq=False, slots=True)
class NetRule:
    raw: str
    pattern: str                    # ABP パターン（正規表現ルールは /.../ の中身）
    is_regex: bool = False
    exception: bool = False
    important: bool = False
    category: str = "ad"
    third_party: Optional[bool] = None
    types: frozenset = frozenset()          # 含める種別（空なら全種別）
    not_types: frozenset = frozenset()
    domains: tuple = ()                     # $domain= 含める
    not_domains: tuple = ()
    removeparam: Optional[str] = None       # $removeparam の値（"" は全パラメーター）
    redirect: Optional[str] = None          # 代替品の名前（$redirect / $redirect-rule）
    redirect_only: bool = False             # $redirect-rule: 他のルールでブロックされたときだけ使う
    redirect_prio: int = 0
    user: bool = False                      # 利用者自身のルール（ユーザールール）
    doc_flags: frozenset = frozenset()      # 例外ルールの document/elemhide/generichide
    _regex: Optional[re.Pattern] = field(default=None, repr=False)
    _bad: bool = False

    @property
    def regex(self) -> Optional[re.Pattern]:
        if self._regex is None and not self._bad:
            try:
                src = self.pattern if self.is_regex else abp_to_regex(self.pattern)
                self._regex = re.compile(src, 0 if "match-case" in self.raw else re.I)
            except re.error:
                self._bad = True
        return self._regex

    def matches(self, url: str, host: str, page_host: str, rtype: str) -> bool:
        if self.types and rtype not in self.types:
            return False
        if self.not_types and rtype in self.not_types:
            return False
        rx = self.regex
        if not (rx and rx.search(url)):
            return False
        if self.third_party is not None and page_host:
            if is_third_party(host, page_host) != self.third_party:
                return False
        if self.domains or self.not_domains:
            ctx = page_host or host
            if self.not_domains and any(_domain_opt_match(ctx, d) for d in self.not_domains):
                return False
            if self.domains and not any(_domain_opt_match(ctx, d) for d in self.domains):
                return False
        return True


def abp_to_regex(p: str) -> str:
    out = []
    i = 0
    if p.startswith("||"):
        out.append(r"^[a-z][a-z0-9+.\-]*://(?:[^/?#]*\.)?")
        i = 2
    elif p.startswith("|"):
        out.append("^")
        i = 1
    end_anchor = p.endswith("|") and len(p) > i
    body = p[i:-1] if end_anchor else p[i:]
    for ch in body:
        if ch == "*":
            out.append(".*")
        elif ch == "^":
            out.append(r"(?:[^\w\-.%]|$)")
        else:
            out.append(re.escape(ch))
    if end_anchor:
        out.append("$")
    return "".join(out)


_TOKEN_RE = re.compile(r"[a-z0-9%]{3,}")
_COMMON_TOKENS = {"http", "https", "www", "com", "net", "org", "html", "php", "js", "jpg",
                  "png", "gif", "css", "jp", "co"}


def _good_tokens(pattern: str) -> list[str]:
    """パターン中で URL のトークン境界と確実に一致するトークンを返す"""
    toks = []
    s = pattern.lower()
    for m in _TOKEN_RE.finditer(s):
        a, b = m.start(), m.end()
        # 両側が固定の非英数字であること（* やパターン端だと URL 上で前後に文字が続き得る）
        left_ok = a > 0 and s[a - 1] != "*"
        right_ok = b < len(s) and s[b] != "*"
        if left_ok and right_ok and m.group() not in _COMMON_TOKENS:
            toks.append(m.group())
    return toks


def literal_piece(r: "NetRule") -> Optional[str]:
    """ルールが一致する URL に必ず含まれる最長の固定文字列（小文字・3 文字以上）"""
    if not r.is_regex:
        p = r.pattern
        if p.startswith("||"):
            p = p[2:]
        p = p.strip("|")
        best = max(re.split(r"[*^]", p), key=len, default="")
        return best.lower() if len(best) >= 3 else None
    src = r.pattern
    # トップレベルに | があると固定文字列は決められない
    depth, i, n = 0, 0, len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            j = src.find("]", i + 2)
            i = (j if j > 0 else n) + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            return None
        i += 1
    runs, cur, i, depth = [], "", 0, 0
    while i < n:
        c = src[i]
        lit = None
        if c == "\\" and i + 1 < n:
            e = src[i + 1]
            if not e.isalnum():
                lit = e
            i += 2
        elif c == "[":
            j = src.find("]", i + 2)
            i = (j if j > 0 else n) + 1
        elif c == "(":
            # グループの中身は任意（|・? の可能性）なので区切りとして扱う
            d, j = 1, i + 1
            while j < n and d:
                if src[j] == "\\":
                    j += 2
                    continue
                d += src[j] == "("
                d -= src[j] == ")"
                j += 1
            i = j
        elif c in ".^$+":
            i += 1
        elif c in "?*{":
            cur = cur[:-1]   # 直前の文字は省略可能
            if c == "{":
                j = src.find("}", i)
                i = (j if j > 0 else n) + 1
            else:
                i += 1
        else:
            lit = c
            i += 1
        if lit is not None and (i >= n or src[i] not in "?*{"):
            cur += lit
            continue
        if lit is not None:
            pass
        runs.append(cur)
        cur = ""
    runs.append(cur)
    best = max(runs, key=len)
    return best.lower() if len(best) >= 3 else None


_URL_TOKEN_RE = re.compile(r"[a-z0-9%]{3,}")


def url_tokens(url: str) -> set[str]:
    return set(_URL_TOKEN_RE.findall(url.lower()))


# --------------------------------------------------------------------------
# エンジン本体
# --------------------------------------------------------------------------
_HOSTS_LINE = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1?|::)\s+([^\s#]+)")
_PLAIN_DOMAIN = re.compile(r"^\|\|([a-z0-9.\-_*]+)\^(\$(.*))?$", re.I)
_HOST_PREFIX = re.compile(r"^\|\|([a-z0-9.\-_]+)([/^:?|].*|)$", re.I)
_SIMPLE_SEL = re.compile(r"^([a-z0-9]*)([.#])([\w-]+)$", re.I)
_ATTR_RE = re.compile(r"""\s(class|id)\s*=\s*["']([^"'<>]{1,500})["']""", re.I)
_COSMETIC_RE = re.compile(r"^([a-z0-9.,~*\-_]*)(#@?[?$%]?#|\$@?\$)(.+)$", re.I)
_DNS_OK_OPTS = {"", "important", "all", "doc", "document", "popup", "~third-party", "1p",
                "first-party", "third-party", "3p"}

# HTML ページを丸ごとブロックすると困るので DNS ブロックしない重要ドメイン
_DNS_NEVER_BLOCK = {"google.com", "youtube.com", "www.youtube.com", "www.google.com",
                    "googlevideo.com", "ytimg.com", "gstatic.com", "googleapis.com",
                    "yahoo.co.jp", "microsoft.com", "windows.com", "localhost"}


class FilterEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self._reset()

    def _reset(self):
        self.dns_block: dict[str, str] = {}       # domain -> category
        self.dns_allow: set[str] = set()
        # 危険サイトのブロックを解除できる例外（利用者のルール・危険サイトのリスト自身）だけ
        self.dns_allow_trusted: set[str] = set()
        self._cur_user = False
        self.tracker_hosts: set[str] = set()      # トラッカー系リストに載っているホスト
        self.ad_hosts: set[str] = set()           # 広告系リストに載っているホスト
        self.security_hosts: set[str] = set()     # マルウェア・フィッシング・採掘スクリプトのホスト
        self.host_rules: dict[str, list[NetRule]] = defaultdict(list)
        self.host_exc: dict[str, list[NetRule]] = defaultdict(list)
        self.token_rules: dict[str, list[NetRule]] = defaultdict(list)
        self.token_exc: dict[str, list[NetRule]] = defaultdict(list)
        self.generic_rules: list[NetRule] = []
        self.generic_exc: list[NetRule] = []
        # トークンを持たないがサイト限定 ($domain=) のルールはページのドメインで索引する
        self.ctx_rules: dict = defaultdict(list)     # (索引キー, ページのドメイン) -> rules
        self.ctx_exc: dict = defaultdict(list)
        self.generic_any: list[NetRule] = []        # パターンが全 URL に一致する（オプションで限定）
        self.generic_any_exc: list[NetRule] = []
        self.param_rules: list[NetRule] = []
        self.tri_rules: dict[str, list[NetRule]] = defaultdict(list)
        self.tri_exc: dict[str, list[NetRule]] = defaultdict(list)
        self._cur_url_l = ""
        self.doc_exc: list[NetRule] = []          # @@...$document / $elemhide / $generichide
        self.generic_hide: set[str] = set()
        self.generic_hide_exc: set[str] = set()
        self.specific_hide: dict[str, set[str]] = defaultdict(set)
        self.specific_exc: dict[str, set[str]] = defaultdict(set)
        self.counts = defaultdict(int)
        self._badfilters: set[str] = set()
        self._generic_css_cache: Optional[str] = None
        # スクリプトレット: ドメイン（"" は全サイト） -> [(名前, 引数, 除外ドメイン)]
        self.scriptlets: dict[str, list] = defaultdict(list)
        self.scriptlet_exc: dict[str, set[str]] = defaultdict(set)   # ドメイン -> {key} （"" は全部無効）
        # 拡張 CSS（手続き型の要素非表示）: ドメイン -> [(key, 手順, 除外ドメイン)]
        self.proc: dict[str, list] = defaultdict(list)
        self.proc_exc: dict[str, set[str]] = defaultdict(set)        # ドメイン（"" は全サイト） -> {key}
        # $redirect / $redirect-rule（ブロックしたときに返す代替品）
        self.redirect_rules: list[NetRule] = []
        self.redirect_exc: list[NetRule] = []

    # ------------------------------------------------------------ 読み込み
    def load(self, sources: list[tuple[str, str, str]]) -> None:
        """sources: [(名前, 本文テキスト, カテゴリ 'ad'|'tracker')]"""
        new = FilterEngine()
        pending: list[tuple[NetRule, list[str]]] = []
        for name, text, cat in sources:
            new._cur_user = name == "user"
            for line in text.splitlines():
                new._parse_line(line.strip(), cat, pending)
        new._index(pending)
        with self.lock:
            self.__dict__.update({k: v for k, v in new.__dict__.items() if k != "lock"})

    def _parse_line(self, line: str, cat: str, pending: list) -> None:
        if not line or line[0] in "!#[" and not (line.startswith("##") or line.startswith("#@#")
                                                  or line.startswith("#?#")):
            return
        if "$badfilter" in line:
            self._badfilters.add(line.replace("$badfilter", "").replace(",badfilter", ""))
            return
        # hosts 形式
        m = _HOSTS_LINE.match(line)
        if m:
            d = m.group(1).lower()
            if d not in ("localhost", "0.0.0.0", "broadcasthost", "local", "ip6-localhost"):
                self._add_dns(d, cat)
            return
        # 要素非表示 / スクリプトレット / HTML フィルタ
        cm = _COSMETIC_RE.match(line)
        if cm:
            self._parse_cosmetic(cm.group(1), cm.group(2), cm.group(3))
            return
        self._parse_network(line, cat, pending)

    def _add_dns(self, d: str, cat: str):
        d = d.strip(".").lower()
        if not d or "*" in d or d in _DNS_NEVER_BLOCK:
            return
        if cat == "annoyance":
            # 迷惑要素リストのドメインは、アプリ全体の DNS では止めない（ブラウザのページ内でだけ扱う）
            return
        if cat == "security":
            # 危険なサイトは他の分類より優先する
            self.dns_block[d] = "security"
            self.security_hosts.add(d)
            self.counts["dns"] += 1
            return
        if self.dns_block.get(d) not in ("tracker", "security"):
            self.dns_block[d] = cat
        (self.tracker_hosts if cat == "tracker" else self.ad_hosts).add(d)
        self.counts["dns"] += 1

    def _parse_cosmetic(self, domains: str, sep: str, body: str):
        if sep in ("##", "#@#") and body.startswith("+js("):
            self._parse_scriptlet(domains, sep == "#@#", body)
            return
        if sep in ("#$#", "#@$#", "#$?#", "#@$?#"):
            self._parse_procedural(domains, "@" in sep, body, injection=True)
            return
        if sep not in ("##", "#@#", "#?#", "#@?#"):
            self.counts["cosmetic_unsupported"] += 1  # AdGuard の JS ルール / HTML フィルタ等
            return
        if body.startswith("+js(") or body.startswith("^"):
            self.counts["cosmetic_unsupported"] += 1
            return
        if _PROCEDURAL.search(body) and procedural.is_procedural(body):
            self._parse_procedural(domains, "@" in sep, body)
            return
        exc = "@" in sep
        doms = [d.strip().lower() for d in domains.split(",") if d.strip()]
        if not doms:
            (self.generic_hide_exc if exc else self.generic_hide).add(body)
        else:
            include = [d for d in doms if not d.startswith("~")]
            if not include:  # ~example.com##.ad -> 汎用扱い（例外ドメインは簡略化のため無視）
                if not exc:
                    self.generic_hide.add(body)
                return
            for d in include:
                (self.specific_exc if exc else self.specific_hide)[d].add(body)
        self.counts["cosmetic"] += 1

    def _parse_procedural(self, domains: str, exc: bool, body: str, injection: bool = False):
        try:
            if injection:
                _sel, task = procedural.parse_css_injection(body)
            else:
                task = procedural.parse(body)
        except procedural.Unsupported:
            self.counts["cosmetic_unsupported"] += 1
            return
        key = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        doms = [d.strip().lower() for d in domains.split(",") if d.strip()]
        include = [d for d in doms if not d.startswith("~")]
        exclude = tuple(d[1:] for d in doms if d.startswith("~"))
        if exc:
            for d in include or [""]:
                self.proc_exc[d].add(key)
            return
        if not include:
            # 全サイト向けの手続き型ルールはページを重くするので使わない（uBlock Origin と同じ扱い）
            self.counts["cosmetic_unsupported"] += 1
            return
        for d in include:
            self.proc[d].append((key, task, exclude))
        self.counts["procedural"] += 1

    def _parse_scriptlet(self, domains: str, exc: bool, body: str):
        parsed = scriptlets.parse(body)
        if parsed is None:
            self.counts["scriptlet_unsupported"] += 1
            return
        name, args = parsed
        doms = [d.strip().lower() for d in domains.split(",") if d.strip()]
        include = [d for d in doms if not d.startswith("~")] or [""]
        exclude = tuple(d[1:] for d in doms if d.startswith("~"))
        if exc:
            k = scriptlets.key(name, args) if name else ""
            for d in include:
                self.scriptlet_exc[d].add(k)
            return
        if not name:
            return
        for d in include:
            self.scriptlets[d].append((name, args, exclude))
        self.counts["scriptlet"] += 1

    def _parse_network(self, line: str, cat: str, pending: list):
        exception = line.startswith("@@")
        if exception:
            line = line[2:]
        opts_str = ""
        if line.startswith("/") and re.match(r"^/.*/(\$[^/]*)?$", line):
            # 正規表現ルール
            m = re.match(r"^/(.*)/(?:\$([^/]*))?$", line)
            pattern, opts_str, is_regex = m.group(1), m.group(2) or "", True
        else:
            is_regex = False
            idx = line.rfind("$")
            if idx >= 0 and re.match(r"^~?[a-z0-9_\-]+(?:=|,|$)", line[idx + 1:], re.I):
                pattern, opts_str = line[:idx], line[idx + 1:]
            else:
                pattern = line
        rule = NetRule(raw=("@@" if exception else "") + line, pattern=pattern, is_regex=is_regex,
                       exception=exception, category=cat, user=self._cur_user)
        types, not_types, flags = set(), set(), set()
        for opt in filter(None, (o.strip() for o in opts_str.split(","))):
            neg = opt.startswith("~")
            key, _, val = opt.lstrip("~").partition("=")
            key = key.lower()
            if key in ("third-party", "3p"):
                rule.third_party = not neg
            elif key in ("first-party", "1p"):
                rule.third_party = neg
            elif key in ("domain", "from"):
                for d in val.split("|"):
                    d = d.strip().lower()
                    if d.startswith("~"):
                        rule.not_domains += (d[1:],)
                    elif d:
                        rule.domains += (d,)
            elif key == "important":
                rule.important = True
            elif key in ("removeparam", "queryprune"):
                rule.removeparam = val
            elif key in ("redirect", "redirect-rule"):
                name, _, prio = val.partition(":")
                rule.redirect = name.strip().lower()
                rule.redirect_only = key == "redirect-rule"
                try:
                    rule.redirect_prio = int(prio) if prio else 0
                except ValueError:
                    rule.redirect_prio = 0
            elif key in ("document", "doc") and exception:
                flags.add("document")
            elif key in ("elemhide", "ehide") and exception:
                flags.add("elemhide")
            elif key in ("generichide", "ghide") and exception:
                flags.add("generichide")
            elif key in TYPE_ALIASES:
                (not_types if neg else types).add(TYPE_ALIASES[key])
            elif key in _UNSUPPORTED_OPTS:
                self.counts["network_unsupported"] += 1
                return
            elif key in _IGNORED_OPTS or key.startswith("_"):
                continue
            else:
                self.counts["network_unsupported"] += 1
                return
        rule.types, rule.not_types, rule.doc_flags = frozenset(types), frozenset(not_types), frozenset(flags)
        if rule.redirect is not None:
            if exception:
                # @@...$redirect は「代替品を使わない」という意味で、通信の許可ではない
                self.redirect_exc.append(rule)
                return
            self.redirect_rules.append(rule)
            self.counts["redirect"] += 1
            if rule.redirect_only:
                return

        # DNS 用ドメインルール
        if not is_regex:
            pm = re.match(r"^\|\|([a-z0-9.\-_]+)\^?\|?$", pattern, re.I)
            if pm:
                host = pm.group(1).lower()
                if not exception and rule.removeparam is None and not rule.domains and cat != "annoyance":
                    {"tracker": self.tracker_hosts, "security": self.security_hosts}.get(cat, self.ad_hosts).add(host)
                if (not types and not rule.domains and not rule.not_domains
                        and rule.removeparam is None
                        and all(o.strip().lstrip("~").split("=")[0].lower() in _DNS_OK_OPTS
                                for o in opts_str.split(","))):
                    if exception:
                        if not flags or flags == {"document"}:
                            self.dns_allow.add(host)
                            if self._cur_user or cat == "security":
                                self.dns_allow_trusted.add(host)
                    else:
                        self._add_dns(host, cat)
        if not pattern and not rule.domains and not flags:
            return
        pending.append(rule)

    def _index(self, pending: list[NetRule]) -> None:
        # badfilter
        if self._badfilters:
            pending = [r for r in pending if r.raw not in self._badfilters]
            self.redirect_rules = [r for r in self.redirect_rules if r.raw not in self._badfilters]
            self.dns_block = {d: c for d, c in self.dns_block.items()
                              if f"||{d}^" not in self._badfilters}
        # トークン頻度
        freq = defaultdict(int)
        cand: dict[int, list[str]] = {}
        for r in pending:
            if r.is_regex:
                continue
            toks = _good_tokens(r.pattern)
            cand[id(r)] = toks
            for t in toks:
                freq[t] += 1
        for r in pending:
            if r.doc_flags:
                # ページ単位の例外。通常のネットワーク例外としては扱わない
                self.doc_exc.append(r)
                continue
            if r.removeparam is not None:
                if not r.exception:
                    self.param_rules.append(r)
                continue
            self.counts["network"] += 1
            site_only = bool(r.domains) and not r.not_domains and all(not d.endswith(".*") for d in r.domains)
            ctxd = self.ctx_exc if r.exception else self.ctx_rules
            hm = None if r.is_regex else _HOST_PREFIX.match(r.pattern)
            if hm and "*" not in hm.group(1):
                key = "h:" + hm.group(1).lower()
                if site_only:
                    for d in r.domains:
                        ctxd[(key, d)].append(r)
                else:
                    (self.host_exc if r.exception else self.host_rules)[key[2:]].append(r)
                continue
            toks = cand.get(id(r)) or []
            if toks:
                best = min(toks, key=lambda t: freq[t])
                if site_only:
                    for d in r.domains:
                        ctxd[("t:" + best, d)].append(r)
                else:
                    (self.token_exc if r.exception else self.token_rules)[best].append(r)
            elif site_only:
                for d in r.domains:
                    ctxd[("*", d)].append(r)
            elif r.is_regex or r.pattern.strip("*|^") :
                (self.generic_exc if r.exception else self.generic_rules).append(r)
            else:
                (self.generic_any_exc if r.exception else self.generic_any).append(r)
        # トークンを持たない汎用ルールは「必ず URL に含まれる文字列」の 3 文字で索引する
        tri_freq = defaultdict(int)
        pieces = {}
        for r in self.generic_rules + self.generic_exc:
            pc = literal_piece(r)
            pieces[id(r)] = pc
            if pc:
                for i in range(len(pc) - 2):
                    tri_freq[pc[i:i + 3]] += 1
        for lst, tri, anyl in ((self.generic_rules, self.tri_rules, self.generic_any),
                               (self.generic_exc, self.tri_exc, self.generic_any_exc)):
            for r in lst:
                pc = pieces.get(id(r))
                if pc:
                    best = min((pc[i:i + 3] for i in range(len(pc) - 2)), key=lambda t: tri_freq[t])
                    tri[best].append(r)
                else:
                    anyl.append(r)
            lst.clear()

    # ------------------------------------------------------------ 照合: DNS
    def dns_lookup(self, domain: str) -> Optional[str]:
        """ブロック対象なら 'ad' / 'tracker' を返す"""
        domain = domain.lower().rstrip(".")
        with self.lock:
            suffixes = list(host_suffixes(domain))
            if any(s in self.dns_allow_trusted for s in suffixes):
                return None
            # 危険なサイトは、フィルターリストの例外ルールでは解除しない（利用者のルールだけが解除できる）
            if any(self.dns_block.get(s) == "security" for s in suffixes):
                return "security"
            for s in suffixes:
                if s in self.dns_allow:
                    return None
            for s in host_suffixes(domain):
                c = self.dns_block.get(s)
                if c:
                    return self.categorize(domain, c)
        return None

    def dns_rule_text(self, domain: str) -> str:
        """ドメイン単位のブロックに一致したルールの表記（||example.com^）"""
        with self.lock:
            for s in host_suffixes(domain):
                if s in self.dns_block:
                    return f"||{s}^"
        return ""

    def categorize(self, host: str, default: str = "ad") -> str:
        """広告/トラッカーの分類。両方のリストに載っている場合はマッチしたルールの分類を使う"""
        in_t = in_a = False
        if default == "security" or any(s in self.security_hosts for s in host_suffixes(host)):
            return "security"
        for s in host_suffixes(host):
            in_t = in_t or s in self.tracker_hosts
            in_a = in_a or s in self.ad_hosts
        if in_t and not in_a:
            return "tracker"
        if in_a and not in_t:
            return "ad"
        return default

    def is_known_tracker(self, host: str) -> bool:
        """広告/トラッカー配信元として知られたドメインか（Cookie 遮断の判定用）"""
        with self.lock:
            for s in host_suffixes(host):
                if s in self.tracker_hosts or s in self.dns_block:
                    return True
        return False

    # ------------------------------------------------------------ 照合: URL
    def _candidates(self, host: str, toks: set[str], exc: bool, page_host: str = ""):
        hd = self.host_exc if exc else self.host_rules
        td = self.token_exc if exc else self.token_rules
        cd = self.ctx_exc if exc else self.ctx_rules
        hs = list(host_suffixes(host))
        ps = list(host_suffixes(page_host or host))
        for s in hs:
            yield from hd.get(s, ())
        for t in toks:
            yield from td.get(t, ())
        if cd:
            keys = ["h:" + s for s in hs] + ["t:" + t for t in toks] + ["*"]
            for k in keys:
                for p in ps:
                    rules = cd.get((k, p))
                    if rules:
                        yield from rules
        yield from (self.generic_any_exc if exc else self.generic_any)
        tri = self.tri_exc if exc else self.tri_rules
        if tri:
            u = self._cur_url_l
            for k in {u[i:i + 3] for i in range(min(len(u), 2048) - 2)}:
                rules = tri.get(k)
                if rules:
                    yield from rules

    def match_url(self, url: str, host: str, page_host: str, rtype: str) -> Optional[NetRule]:
        """ブロックすべきなら該当ルールを返す（例外ルールで許可された場合は None）"""
        url_l = url
        toks = url_tokens(url)
        with self.lock:
            self._cur_url_l = url.lower()
            block = None
            for r in self._candidates(host, toks, False, page_host):
                if r.matches(url_l, host, page_host, rtype):
                    block = r
                    if r.important:
                        break
            if block is None:
                return None
            for r in self._candidates(host, toks, True, page_host):
                if r.matches(url_l, host, page_host, rtype):
                    if block.important and not r.important:
                        continue
                    if block.category == "security" and not (r.user or r.category == "security"):
                        # 危険サイトのブロックは、広告などのリストの例外ルールでは解除しない
                        continue
                    return None
            return block

    def redirect_for(self, url: str, host: str, page_host: str, rtype: str) -> Optional[str]:
        """ブロックした通信に返す代替品の名前（$redirect / $redirect-rule）。無ければ None"""
        with self.lock:
            if not self.redirect_rules:
                return None
            best = None
            for r in self.redirect_rules:
                if (best is None or r.redirect_prio > best.redirect_prio) and r.matches(url, host, page_host, rtype):
                    best = r
            if best is None:
                return None
            for r in self.redirect_exc:
                if r.redirect in ("", best.redirect) and r.matches(url, host, page_host, rtype):
                    return None
            return None if best.redirect in ("", "none") else best.redirect

    def page_flags(self, page_url: str, page_host: str) -> set[str]:
        """ページ単位の例外 (document=サイト全体許可 / elemhide / generichide)"""
        out = set()
        with self.lock:
            for r in self.doc_exc:
                if (not r.pattern or (r.regex and r.regex.search(page_url))) and (
                        not r.domains or any(_domain_opt_match(page_host, d) for d in r.domains)):
                    out |= r.doc_flags
        return out

    def params_to_remove(self, url: str, host: str, page_host: str, rtype: str) -> list[str]:
        out = []
        with self.lock:
            for r in self.param_rules:
                if not r.pattern and not r.domains:
                    out.append(r.removeparam)
                elif r.matches(url, host, page_host, rtype):
                    out.append(r.removeparam)
        return out

    # ------------------------------------------------------------ 要素非表示
    def scriptlets_for(self, host: str) -> list[tuple[str, tuple[str, ...]]]:
        """そのサイトで実行するスクリプトレット [(名前, 引数)]"""
        with self.lock:
            keys = cosmetic_keys(host)
            excs: set[str] = set(self.scriptlet_exc.get("", ()))
            for k in keys:
                excs |= self.scriptlet_exc.get(k, set())
            if "" in excs:
                return []
            out, seen = [], set()
            for k in keys + [""]:
                for name, args, exclude in self.scriptlets.get(k, ()):
                    sk = scriptlets.key(name, args)
                    if sk in seen or sk in excs:
                        continue
                    if exclude and any(s in exclude for s in host_suffixes(host)):
                        continue
                    seen.add(sk)
                    out.append((name, args))
            return out

    def procedural_for(self, host: str) -> tuple[list[dict], list[str]]:
        """そのサイトの拡張 CSS: (ページ内スクリプトで実行する手順, そのまま差し込める CSS)"""
        with self.lock:
            keys = cosmetic_keys(host)
            excs: set[str] = set(self.proc_exc.get("", ()))
            for k in keys:
                excs |= self.proc_exc.get(k, set())
            tasks, css, seen = [], [], set()
            for k in keys:
                for key, task, exclude in self.proc.get(k, ()):
                    if key in seen or key in excs:
                        continue
                    if exclude and any(s in exclude for s in host_suffixes(host)):
                        continue
                    seen.add(key)
                    rule = procedural.plain_css_rule(task)
                    if rule:
                        css.append(rule)
                    else:
                        tasks.append(task)
            return tasks, css

    def specific_selectors(self, host: str) -> list[str]:
        with self.lock:
            sels, excs = set(), set(self.generic_hide_exc)
            for s in cosmetic_keys(host):
                sels |= self.specific_hide.get(s, set())
                excs |= self.specific_exc.get(s, set())
            return sorted(sels - excs)

    def generic_exceptions(self, host: str) -> list[str]:
        with self.lock:
            excs = set()
            for s in cosmetic_keys(host):
                excs |= self.specific_exc.get(s, set())
            return sorted(excs & self.generic_hide)

    # 汎用要素非表示は 2 種類に分けて扱う:
    #   単純セレクタ (.class / #id / tag.class) … ページに存在するクラス・ID の分だけ埋め込む
    #   複合セレクタ … 小さい CSS ファイルとして全ページに適用（ブラウザにキャッシュされる）
    # 1 万個以上のセレクタを丸ごと適用するとページの描画が重くなるため（uBlock Origin と同じ方式）。
    def _build_generic(self):
        if self._generic_css_cache is not None:
            return
        cls: dict = defaultdict(list)
        ids: dict = defaultdict(list)
        complex_, has = [], []
        for sel in sorted(self.generic_hide - self.generic_hide_exc):
            m = _SIMPLE_SEL.match(sel)
            if m:
                (cls if m.group(2) == "." else ids)[m.group(3)].append(m.group(1).lower())
            elif ":has(" in sel:
                # :has() を全ページの CSS に入れると DOM 変更のたびに再計算が走り非常に重くなる。
                # ページ内スクリプトがときどき querySelectorAll で照合する
                has.append(sel)
            else:
                complex_.append(sel)
        self._generic_cls, self._generic_ids = dict(cls), dict(ids)
        self._generic_complex_css = selectors_to_css(complex_)
        self._generic_json = json.dumps({"c": self._generic_cls, "i": self._generic_ids, "h": has},
                                        separators=(",", ":"))
        self._generic_css_cache = selectors_to_css(sorted(self.generic_hide - self.generic_hide_exc))

    def generic_css(self) -> str:
        """全汎用セレクタ（互換用）"""
        with self.lock:
            self._build_generic()
            return self._generic_css_cache

    def generic_complex_css(self) -> str:
        with self.lock:
            self._build_generic()
            return self._generic_complex_css

    def generic_simple_json(self) -> str:
        with self.lock:
            self._build_generic()
            return self._generic_json

    def generic_for_html(self, html: str) -> list[str]:
        """HTML に現れるクラス・ID に一致する汎用セレクタだけを返す"""
        with self.lock:
            self._build_generic()
            cls, ids = self._generic_cls, self._generic_ids
        out = []
        seen = set()
        for m in _ATTR_RE.finditer(html):
            kind, val = m.group(1).lower(), m.group(2)
            names = val.split() if kind == "class" else [val.strip()]
            table = cls if kind == "class" else ids
            mark = "." if kind == "class" else "#"
            for n in names:
                if (mark, n) in seen:
                    continue
                seen.add((mark, n))
                tags = table.get(n)
                if tags:
                    out.extend(f"{t}{mark}{n}" for t in set(tags))
        return out

    def summary(self) -> dict:
        with self.lock:
            return {
                "dns_domains": len(self.dns_block),
                "network_rules": self.counts["network"] + len(self.param_rules),
                "cosmetic_generic": len(self.generic_hide),
                "cosmetic_specific": sum(len(v) for v in self.specific_hide.values()) + self.counts["procedural"],
                "scriptlets": self.counts["scriptlet"],
                "unsupported": (self.counts["network_unsupported"] + self.counts["cosmetic_unsupported"]
                                + self.counts["scriptlet_unsupported"]),
            }


_DOMAIN_RULE = re.compile(r"^(?:@@)?\|\|[a-z0-9.*_\-]+\^\|?(?:\$[a-z0-9,~=_\-]*)?$", re.I)


# ドメインの一覧だけのリストで使ってよいオプション。$document（サイト全体の除外）や $badfilter（他のリストの
# ルールの無効化）などは、リストの外にまで影響するので使わない
_SAFE_DOMAIN_OPTS = {"important", "third-party", "~third-party", "3p", "~3p", "1p", "first-party", "all"}


def _safe_domain_opts(rule: str) -> bool:
    _, sep, opts = rule.partition("$")
    return not sep or all(o.strip().lower() in _SAFE_DOMAIN_OPTS for o in opts.split(",") if o.strip())


def domains_only(text: str) -> tuple[str, int]:
    """ドメインの一覧だけのリスト（DNS 用のリスト・hosts 形式）から、ドメイン単位のルール以外を取り除く。

    配布元が乗っ取られて細工されたリストが配られても、要素の非表示・スクリプトレット・
    URL のパターン・ページ単位の例外などが紛れ込まないようにする。(残した本文, 取り除いた行数)
    """
    keep, dropped = [], 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("!") or (s.startswith("#") and not s.startswith("##") and not s.startswith("#@")):
            continue
        if _HOSTS_LINE.match(s) or (_DOMAIN_RULE.match(s) and _safe_domain_opts(s)):
            keep.append(s)
        else:
            dropped += 1
    return "\n".join(keep), dropped


def selectors_to_css(sels: list[str], chunk: int = 20) -> str:
    """セレクタ群を display:none の CSS にする。1 つの不正セレクタで全体が無効にならないよう分割"""
    out = []
    for i in range(0, len(sels), chunk):
        out.append(",\n".join(sels[i:i + chunk]) + "{display:none!important}")
    return "\n".join(out)


def load_list_files(paths_with_cat: list[tuple[Path, str]]) -> list[tuple[str, str, str]]:
    out = []
    for p, cat in paths_with_cat:
        try:
            out.append((p.name, p.read_text(encoding="utf-8", errors="replace"), cat))
        except OSError:
            pass
    return out
