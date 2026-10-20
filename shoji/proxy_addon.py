# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""HTTPS フィルタリングプロキシ（mitmproxy アドオン）。

ブラウザ・アプリの通信を中継し、以下を行う。
  * 広告 / トラッカーの URL をブロック（通信そのものを発生させない＝通信量節約・高速化）
  * YouTube のプレイヤー応答・フィード応答から動画広告を除去
  * ステルスモード（追跡パラメーター・Cookie・リファラー・Client Hints 等の除去）
  * AMP ページを通常ページへ転送
  * HTML に要素非表示 CSS とページ内スクリプト（ポップアップ・再挿入対策等）を埋め込む
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import parse_qs, urlsplit

from mitmproxy import http, tls
from mitmproxy.net.http.headers import infer_content_encoding

from . import injector, lists, redirects, reqlog, scriptlets, winsys, youtube
from .config import BUILTIN_HTTPS_EXCLUSIONS, CERT_DIR, DEFAULT_SHORTCUTS, is_whitelisted
from .context import AppContext
from .i18n import lang, t
from .injector import MAGIC_HOST, MAGIC_ORIGIN
from .privacy import (CLIENT_HINT_HEADERS, amp_canonical, amp_redirect_url, generic_user_agent,
                      is_search_engine, is_third_party, limit_cookie_age, origin_of,
                      strip_tracking_params)

_DEST_MAP = {
    "document": "document", "iframe": "sub_frame", "frame": "sub_frame", "fencedframe": "sub_frame",
    "script": "script", "worker": "script", "sharedworker": "script", "serviceworker": "script",
    "audioworklet": "script", "paintworklet": "script", "image": "image", "style": "stylesheet",
    "font": "font", "video": "media", "audio": "media", "track": "media", "object": "object",
    "embed": "object", "report": "ping", "manifest": "other", "xslt": "other",
}
_EXT_MAP = [
    (re.compile(r"\.(m?js)(\?|$)", re.I), "script"),
    (re.compile(r"\.(png|jpe?g|gif|webp|avif|svg|ico|bmp)(\?|$)", re.I), "image"),
    (re.compile(r"\.css(\?|$)", re.I), "stylesheet"),
    (re.compile(r"\.(mp4|webm|m3u8|ts|m4s|mp3|aac|vtt|mpd)(\?|$)", re.I), "media"),
    (re.compile(r"\.(woff2?|ttf|otf)(\?|$)", re.I), "font"),
]
_PAGE_REPORT_KINDS = {"popup": "document", "cosmetic": None, "reinserted": None, "amp": None,
                      "youtube": None, "stealth_param": None, "security": "document"}


def _should_block(cat: str, F: dict) -> bool:
    """分類と機能設定から、ブロックするかを決める"""
    if cat == "security":
        return F.get("block_malware", True)
    if cat == "tracker":
        return F["block_trackers"]
    return F["block_ads"]          # ad / annoyance


def guess_type(req: http.Request) -> str:
    dest = req.headers.get("sec-fetch-dest", "").lower()
    if dest in _DEST_MAP:
        return _DEST_MAP[dest]
    if req.headers.get("ping-from") or req.headers.get("content-type", "").startswith("text/ping"):
        return "ping"
    if dest == "empty":
        if req.method == "POST" and req.headers.get("sec-fetch-mode") == "no-cors":
            return "ping"   # sendBeacon
        return "xmlhttprequest"
    if req.headers.get("upgrade", "").lower() == "websocket":
        return "websocket"
    path = req.path
    for rx, rtype in _EXT_MAP:
        if rx.search(path.split("#")[0]):
            return rtype
    if "text/html" in req.headers.get("accept", "") and req.method == "GET":
        return "document"
    return "other"


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


# 要素の選択ブロックで受け付けない、ブラウザの CSS ではない拡張構文
_PROCEDURAL_MARK = re.compile(r":(?:-abp-|has-text|xpath|upward|remove\(|style\(|matches-|min-text|watch-attr|others)", re.I)


class ShojiAddon:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self._flag_cache: OrderedDict = OrderedDict()
        self._client_proc: dict = {}
        self._flag_ver = ""

    # ------------------------------------------------------------ 補助
    @property
    def engine(self):
        return self.ctx.engine

    def _passthrough(self, host: str) -> bool:
        """HTTPS を復号しない（中身を見ない）ホストか"""
        if host == MAGIC_HOST:
            return False
        cfg = self.ctx.cfg
        if self.ctx.paused or not cfg["features"].get("https_filtering", True):
            return True
        if not self.ctx.https_ready:
            # 証明書がブラウザに信頼されていない状態で復号すると、全サイトが証明書エラーになる
            return True
        if host in self.ctx.passthrough_hosts:
            return True
        if is_whitelisted(host, cfg.get("https_exclusions", [])) or is_whitelisted(host, BUILTIN_HTTPS_EXCLUSIONS):
            return True
        return self.ctx.is_allowed(host)

    def _passthrough_reason(self, host: str) -> str:
        cfg = self.ctx.cfg
        if self.ctx.paused:
            return t("pt.paused")
        if not cfg["features"].get("https_filtering", True):
            return t("pt.off")
        if not self.ctx.https_ready:
            return t("pt.nocert")
        if host in self.ctx.passthrough_hosts:
            return t("pt.auto")
        if is_whitelisted(host, BUILTIN_HTTPS_EXCLUSIONS):
            return t("pt.builtin")
        if is_whitelisted(host, cfg.get("https_exclusions", [])):
            return t("pt.user")
        return t("pt.allow")

    def _page_flags(self, page_url: str, page_host: str) -> set[str]:
        if self._flag_ver != self.ctx.rules_version:
            self._flag_cache.clear()
            self._flag_ver = self.ctx.rules_version
        key = page_host
        if key in self._flag_cache:
            self._flag_cache.move_to_end(key)
            return self._flag_cache[key]
        flags = self.engine.page_flags(page_url, page_host)
        self._flag_cache[key] = flags
        if len(self._flag_cache) > 2000:
            self._flag_cache.popitem(last=False)
        return flags

    @staticmethod
    def _respond(flow: http.HTTPFlow, status: int, body: bytes | str, ctype: str,
                 extra: dict | None = None) -> None:
        headers = {"Content-Type": ctype, "Cache-Control": "no-store", "X-Shoji": "blocked",
                   "Access-Control-Allow-Origin": flow.request.headers.get("origin", "*")}
        if extra:
            headers.update(extra)
        flow.response = http.Response.make(status, body, headers)

    # ------------------------------------------------------------ CONNECT / TLS
    def http_connect(self, flow: http.HTTPFlow) -> None:
        host = flow.request.host.lower()
        if host == MAGIC_HOST or self.ctx.paused or not self._passthrough(host) or self.ctx.is_allowed(host):
            return
        # 復号しないホストでも、ドメイン単位の広告/トラッカーはここで遮断する
        cat = self.engine.dns_lookup(host)
        F = self.ctx.cfg["features"]
        if cat and _should_block(cat, F):
            self.ctx.stats.record(cat, "proxy", host, "other", detail="CONNECT " + host)
            self.ctx.reqlog.add(reqlog.BLOCKED, f"https://{host}/", host, method="CONNECT", cat=cat,
                                rule=self.engine.dns_rule_text(host),
                                detail=t("log.connect"))
            flow.response = http.Response.make(403, b"", {"X-Shoji": "blocked"})

    async def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        sni = (data.client_hello.sni or (data.context.server.address or ("",))[0] or "").lower()
        if sni and self._passthrough(sni):
            data.ignore_connection = True
            self.ctx.reqlog.add(reqlog.PASSTHROUGH, f"https://{sni}/", sni, method="TLS",
                                detail=self._passthrough_reason(sni))
            return
        # 接続元のアプリを調べる。証明書を受け付けないアプリ（独自の証明書ストアを使うアプリや
        # 証明書ピンニングをするアプリ）は、そのアプリの通信だけ復号せずに通す。
        # 他のアプリ（Edge 等）でのフィルタリングには影響させない。
        if sni and winsys.IS_WIN and (self.ctx.untrusting_apps or not self.ctx.is_tls_ok(sni)):
            port = data.context.client.peername[1] if data.context.client.peername else 0
            try:
                proc = await asyncio.get_running_loop().run_in_executor(
                    None, winsys.process_for_client, port, int(self.ctx.cfg["proxy"]["listen_port"]))
            except Exception:  # noqa: BLE001
                proc = ""
            if proc and proc in self.ctx.untrusting_apps:
                data.ignore_connection = True
                self.ctx.reqlog.add(reqlog.PASSTHROUGH, f"https://{sni}/", sni, method="TLS",
                                    detail=t("log.untrusting", app=proc))
                return
            self._client_proc[data.context.client.id] = proc
            if len(self._client_proc) > 5000:
                self._client_proc.clear()

    def tls_established_client(self, data: tls.TlsData) -> None:
        sni = (data.conn.sni or "").lower()
        self._client_proc.pop(data.conn.id, None)
        if sni:
            self.ctx.tls_ok(sni)

    def tls_failed_client(self, data: tls.TlsData) -> None:
        sni = (data.conn.sni or "").lower()
        err = str(data.conn.error or "")
        proc = self._client_proc.pop(data.conn.id, "")
        # 途中で切断されただけ（ブラウザの先読み接続のキャンセル等）は証明書の拒否ではない
        if not sni or not err.startswith("The client does not trust the proxy's certificate"):
            return
        if proc:
            if self.ctx.add_untrusting_app(proc):
                hint = t("msg.ff_hint") if winsys.is_own_store_browser(proc) else ""
                print(t("msg.app_untrust", app=proc, hint=hint))
            return
        # 接続元アプリが分からない場合だけ、ホスト単位で除外する
        r = self.ctx.tls_failed(sni)
        if r == "host":
            print(t("msg.host_untrust", host=sni))
        elif r == "global":
            print(t("msg.global_untrust"))

    # ------------------------------------------------------------ リクエスト
    def request(self, flow: http.HTTPFlow) -> None:
        req = flow.request
        host = req.pretty_host.lower()
        if host == MAGIC_HOST:
            return self._serve_magic(flow)
        stats = self.ctx.stats
        stats.count_request("proxy")
        cfg = self.ctx.cfg
        F, S = cfg["features"], cfg["stealth"]
        rtype = guess_type(req)
        url = req.pretty_url
        if rtype == "document":
            page_host = host
        else:
            page_host = _host_of(req.headers.get("origin", "")) or _host_of(req.headers.get("referer", ""))
        meta = {"rtype": rtype, "page_host": page_host, "notes": []}
        flow.metadata["kk"] = meta
        log = self.ctx.reqlog
        if host in ("127.0.0.1", "localhost", "::1") and req.port == int(cfg["dashboard"]["listen_port"]):
            meta["allowed"] = True      # ダッシュボード自身は記録も加工もしない
            return

        def _log(action, **kw):
            meta["log"] = log.add(action, url, host, rtype=rtype, method=req.method, page=page_host, **kw)

        if (not self.ctx.paused and F.get("block_malware", True) and page_host and page_host != host
                and self.ctx.is_allowed(page_host) and not self.ctx.is_allowed(host)):
            # 許可リストのサイトに埋め込まれた他サイトの通信でも、危険サイトだけは止める
            rule = self.engine.match_url(url, host, page_host, rtype)
            if rule and self.engine.categorize(host, rule.category) == "security":
                _log(reqlog.BLOCKED, rule=rule.raw, cat="security")
                return self._block(flow, rule, "security", rtype, host, url)
        if self.ctx.paused or self.ctx.is_allowed(host, page_host):
            meta["allowed"] = True
            _log(reqlog.ALLOWED, detail=t("log.paused") if self.ctx.paused else t("log.allowlist"))
            return
        if page_host and "document" in self._page_flags(
                req.headers.get("referer") or f"https://{page_host}/", page_host):
            meta["allowed"] = True
            _log(reqlog.ALLOWED, detail=t("log.docexc"))
            return

        # AMP → 通常ページ
        if F["disable_amp"] and rtype == "document" and req.method == "GET":
            target = amp_redirect_url(url)
            if target:
                stats.record("amp", "proxy", host, count_bytes=False, detail=url)
                _log(reqlog.MODIFIED, detail=t("log.amp", url=target))
                self._respond(flow, 302, b"", "text/plain", {"Location": target})
                return

        # ステルス: 追跡パラメーターの除去
        if S["enabled"] and S["strip_tracking_params"] and "?" in url and req.method in ("GET", "HEAD"):
            extra = self.engine.params_to_remove(url, host, page_host, rtype)
            new_url, removed = strip_tracking_params(url, extra, generic=(rtype == "document"))
            if removed:
                stats.record("stealth_param", "proxy", host, count=len(removed), count_bytes=False,
                             detail=",".join(removed))
                meta["notes"].append(t("log.params", params=", ".join(removed)))
                if rtype == "document":
                    _log(reqlog.MODIFIED, detail=meta["notes"][-1])
                    self._respond(flow, 302, b"", "text/plain", {"Location": new_url})
                    return
                req.url = new_url
                url = new_url

        # 広告 / トラッカー / 危険なサイトのブロック
        if F["block_ads"] or F["block_trackers"] or F.get("block_malware", True):
            rule = self.engine.match_url(url, host, page_host, rtype)
            if rule:
                cat = self.engine.categorize(host, rule.category)
                if _should_block(cat, F):
                    redir = self._redirect_name(url, host, page_host, rtype)
                    _log(reqlog.BLOCKED, rule=rule.raw, cat=cat,
                         detail=t("log.redirect", name=redir) if redir else "")
                    return self._block(flow, rule, cat, rtype, host, url, redir)

        if S["enabled"]:
            self._stealth_request(flow, host, page_host, rtype, S)
        if rtype == "document" and F["https_filtering"]:
            # キャッシュの再検証（304）だと、前回埋め込んだ古いルールのままのページが使われるため、毎回取り直す
            for name in ("if-none-match", "if-modified-since"):
                if name in req.headers:
                    del req.headers[name]
        _log(reqlog.MODIFIED if meta["notes"] else reqlog.PASSED, detail=" / ".join(meta["notes"]))

    def _redirect_name(self, url, host, page_host, rtype) -> str:
        """ブロックした通信に返す代替品の名前（無ければ ""）"""
        if rtype == "document":
            return ""
        name = self.engine.redirect_for(url, host, page_host, rtype)
        if name and redirects.get(name):
            return redirects.canonical(name) or name
        return redirects.builtin_for(url, rtype) or ""

    def _block(self, flow, rule, cat, rtype, host, url, redir=""):
        stats = self.ctx.stats
        stats.record(cat, "proxy", host, rtype, detail=rule.raw)
        if cat == "ad" and (youtube.is_youtube_host(host)
                            or youtube.is_youtube_host(flow.metadata["kk"]["page_host"] or "")):
            stats.record("youtube", "proxy", host, rtype, count_bytes=False, detail=url[:200])
        res = redirects.get(redir) if redir else None
        if res and rtype != "document":
            ctype, body = res
            self._respond(flow, 200, body, ctype, {"X-Shoji": "redirect"})
        elif rtype == "document":
            self._respond(flow, 200, injector.blocked_page_html(url, host, cat, rule.raw,
                                                                self.ctx.issue_token("allow", host)),
                          "text/html; charset=utf-8")
        elif rtype == "sub_frame":
            self._respond(flow, 200, injector.blocked_frame_html(), "text/html; charset=utf-8")
        elif rtype == "script":
            self._respond(flow, 200, b"/* blocked by Shoji */", "application/javascript")
        elif rtype == "stylesheet":
            self._respond(flow, 200, b"", "text/css")
        elif rtype == "image":
            # 壊れた画像のアイコンが出ないよう、透明な画像を返す
            self._respond(flow, 200, redirects.GIF_1x1, "image/gif")
        elif rtype == "ping":
            self._respond(flow, 204, b"", "text/plain")
        else:
            self._respond(flow, 403, b"", "text/plain")

    def _stealth_request(self, flow, host, page_host, rtype, S):
        h = flow.request.headers
        changed = 0
        if S["send_dnt"]:
            h["DNT"] = "1"
            h["Sec-GPC"] = "1"
        if S["remove_x_client_data"] and "x-client-data" in h:
            del h["x-client-data"]
            changed += 1
        if S["strip_client_hints"]:
            for name in CLIENT_HINT_HEADERS:
                if name in h:
                    del h[name]
                    changed += 1
        if S["hide_user_agent"] and "user-agent" in h:
            ua = generic_user_agent(h["user-agent"])
            if ua != h["user-agent"]:
                h["user-agent"] = ua
                changed += 1
        ref = h.get("referer", "")
        if ref:
            rhost = _host_of(ref)
            third = is_third_party(host, rhost)
            if third and ((S["hide_search_queries"] and is_search_engine(rhost)) or S["trim_referer"]):
                o = origin_of(ref)
                if o and o != ref:
                    h["referer"] = o
                    changed += 1
        if (S["block_third_party_cookies"] and page_host and is_third_party(host, page_host)
                and self.engine.is_known_tracker(host)):
            flow.metadata["kk"]["strip_set_cookie"] = True
            if "cookie" in h:
                del h["cookie"]
                flow.metadata["kk"]["notes"].append(t("log.cookie"))
                self.ctx.stats.record("stealth_cookie", "proxy", host, count_bytes=False,
                                      detail="Cookie 送信を遮断")
        if changed:
            self.ctx.stats.record("stealth_header", "proxy", "", count=1, count_bytes=False)

    def error(self, flow: http.HTTPFlow) -> None:
        meta = flow.metadata.get("kk")
        e = meta.get("log") if meta else None
        if e is not None and flow.error:
            e["status"] = -1
            e["detail"] = ((e["detail"] + " / ") if e["detail"] else "") + t("log.conn_error") + ": " + str(flow.error.msg)[:120]

    # ------------------------------------------------------------ レスポンス
    def responseheaders(self, flow: http.HTTPFlow) -> None:
        meta = flow.metadata.get("kk")
        resp = flow.response
        if not meta or not resp or meta.get("allowed"):
            if resp:
                resp.stream = True
            return
        S = self.ctx.cfg["stealth"]
        host = flow.request.pretty_host.lower()
        # Cookie の受信遮断・寿命制限
        if S["enabled"] and "set-cookie" in resp.headers:
            if meta.get("strip_set_cookie"):
                n = len(resp.headers.get_all("set-cookie"))
                del resp.headers["set-cookie"]
                self.ctx.stats.record("stealth_cookie", "proxy", host, count=n, count_bytes=False,
                                      detail="トラッカー Cookie の保存を遮断")
            else:
                hours = S.get("first_party_cookie_max_age_hours") or 0
                if hours > 0:
                    resp.headers.set_all("set-cookie", [limit_cookie_age(c, int(hours * 3600))
                                                        for c in resp.headers.get_all("set-cookie")])
        ct = resp.headers.get("content-type", "").lower()
        need = False
        if resp.status_code == 200 and "text/html" in ct and meta["rtype"] in ("document", "sub_frame", "other") \
                and flow.request.method == "GET":
            need = True
        elif youtube.is_youtube_api(host, flow.request.path) and "json" in ct:
            need = True
        if not need:
            resp.stream = True

    def response(self, flow: http.HTTPFlow) -> None:
        resp = flow.response
        meta = flow.metadata.get("kk")
        if meta and resp and meta.get("log"):
            meta["log"]["status"] = resp.status_code
        if not meta or not resp or resp.stream or meta.get("allowed") or flow.request.pretty_host == MAGIC_HOST:
            return
        cfg = self.ctx.cfg
        F, S = cfg["features"], cfg["stealth"]
        host = flow.request.pretty_host.lower()
        ct = resp.headers.get("content-type", "").lower()
        stats = self.ctx.stats

        if "json" in ct and youtube.is_youtube_api(host, flow.request.path):
            if F["youtube_ads"] and resp.content:
                new, n = youtube.prune_json_bytes(resp.content)
                if n:
                    resp.content = new
                    stats.record("ad", "proxy", host, "media", count=n, detail="YouTube 動画広告 (API)")
                    stats.record("youtube", "proxy", host, "media", count=n, count_bytes=False,
                                 detail=flow.request.path)
                    self.ctx.reqlog.add(reqlog.MODIFIED, flow.request.pretty_url, host, rtype="xmlhttprequest",
                                        page=meta.get("page_host", ""), cat="ad",
                                        detail=t("log.youtube", n=n))
            return

        if "text/html" not in ct or resp.status_code != 200 or not resp.content:
            return
        raw = resp.content
        enc = infer_content_encoding(resp.headers.get("content-type", ""), raw[:4096])
        try:
            text = raw.decode(enc, "surrogateescape")
        except (LookupError, UnicodeError):
            enc = "utf-8"
            text = raw.decode(enc, "surrogateescape")
        url = flow.request.pretty_url
        modified = False

        if F["disable_amp"] and meta["rtype"] == "document":
            canon = amp_canonical(text[:30000], url)
            if canon and _host_of(canon):
                stats.record("amp", "proxy", host, count_bytes=False, detail=f"{url} → {canon}")
                flow.response = http.Response.make(302, b"", {"Location": canon, "Cache-Control": "no-store"})
                return

        if F["youtube_ads"] and youtube.is_youtube_host(host):
            text, n = youtube.prune_html(text)
            if n:
                modified = True
                stats.record("ad", "proxy", host, "media", count=1, detail="YouTube 動画広告 (ページ)")
                stats.record("youtube", "proxy", host, "media", count=n, count_bytes=False, detail=url[:200])
                self.ctx.reqlog.add(reqlog.MODIFIED, url, host, rtype="document", page=host, cat="ad",
                                    detail=t("log.youtube", n=n))

        flags = self._page_flags(url, host)
        if "document" not in flags and F["https_filtering"]:
            use_specific = F["cosmetic"] and "elemhide" not in flags
            use_generic = F["cosmetic"] and not ({"elemhide", "generichide"} & flags)
            specific = self.engine.specific_selectors(host) if use_specific else []
            exceptions = self.engine.generic_exceptions(host) if use_generic else []
            generic_inline = self.engine.generic_for_html(text) if use_generic else []
            page_cfg = {
                "f": {k: bool(v) for k, v in F.items()},
                "s": {k: v for k, v in S.items()},
                "magic": MAGIC_ORIGIN,
                "sel": specific,
                "exc": exceptions,
                "gen": use_generic,
                "v": self.ctx.rules_version,
                "lang": lang(),
                "keys": {**DEFAULT_SHORTCUTS, **((cfg.get("app") or {}).get("shortcuts") or {})},
            }
            proc_tasks, proc_css = self.engine.procedural_for(host) if use_specific else ([], [])
            calls = (self.engine.scriptlets_for(host)
                     if F.get("scriptlets", True) and "elemhide" not in flags else [])
            snippet, sh, csh = injector.build_snippet(page_cfg, specific, exceptions, generic_inline,
                                                      use_generic, self.ctx.rules_version,
                                                      scriptlets.build(calls), proc_tasks, proc_css)
            text = injector.inject(text, snippet)
            modified = True
            parts = []
            if specific:
                parts.append(t("log.page.specific", n=len(specific)))
            if generic_inline:
                parts.append(t("log.page.generic", n=len(generic_inline)))
            if proc_tasks or proc_css:
                parts.append(t("log.page.procedural", n=len(proc_tasks) + len(proc_css)))
            if calls:
                names = list(dict.fromkeys(n for n, _ in calls))
                parts.append(t("log.page.scriptlets", n=len(calls),
                               names=", ".join(names[:6]) + (" …" if len(names) > 6 else "")))
            self.ctx.reqlog.add(reqlog.PAGE, url, host, rtype=meta["rtype"], page=host,
                                detail=" / ".join(parts) or t("log.page.default"))
            for name in ("content-security-policy", "content-security-policy-report-only"):
                vals = resp.headers.get_all(name)
                if vals:
                    resp.headers.set_all(name, [injector.patch_csp(v, sh, csh) for v in vals])
        if modified:
            resp.content = text.encode(enc, "surrogateescape")
            resp.headers.pop("content-md5", None)
            # 加工したページはブラウザに保存させない。保存されると、サイトを許可したりルールを変えたりしても
            # 古い加工済みのページが使われてしまう
            resp.headers["cache-control"] = "no-store"
            for name in ("etag", "last-modified", "expires"):
                resp.headers.pop(name, None)

    # ------------------------------------------------------------ 内部エンドポイント
    def _serve_magic(self, flow: http.HTTPFlow) -> None:
        req = flow.request
        path = req.path.split("?")[0]
        cors = {"Access-Control-Allow-Origin": req.headers.get("origin", "*"),
                "Access-Control-Allow-Credentials": "true", "Access-Control-Allow-Headers": "*"}
        if req.method == "OPTIONS":
            flow.response = http.Response.make(204, b"", cors)
        elif path in ("/generic.css", "/generic-complex.css"):
            body = self.engine.generic_css() if path == "/generic.css" else self.engine.generic_complex_css()
            flow.response = http.Response.make(200, body.encode("utf-8"), {
                "Content-Type": "text/css; charset=utf-8",
                "Cache-Control": "public, max-age=86400", **cors})
        elif path == "/generic-simple.json":
            flow.response = http.Response.make(200, self.engine.generic_simple_json().encode("utf-8"), {
                "Content-Type": "application/json", "Cache-Control": "public, max-age=86400", **cors})
        elif path == "/report" and req.method == "POST":
            self._page_report(req)
            flow.response = http.Response.make(204, b"", cors)
        elif path == "/user-rule" and req.method == "POST":
            ok, payload = self._picker_rule(req)
            flow.response = http.Response.make(200 if ok else 400, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                               {"Content-Type": "application/json", "Cache-Control": "no-store", **cors})
        elif path == "/allow-site":
            self._allow_site(flow, req)
        elif path == "/allow":
            qs = parse_qs(urlsplit(req.pretty_url).query)
            target = qs.get("url", [""])[0]
            h = _host_of(target)
            # ブロック画面のボタンから来たときだけ許可する（他のページが勝手に許可できないように）
            if h and target.startswith(("http://", "https://")) and self.ctx.use_token(qs.get("t", [""])[0], "allow", h):
                self.ctx.allow_temporarily(h)
                flow.response = http.Response.make(302, b"", {"Location": target, "Cache-Control": "no-store"})
            else:
                flow.response = http.Response.make(400, b"bad url", {"Content-Type": "text/plain"})
        elif path in ("/cert", "/cert.cer", "/cert.pem"):
            p = CERT_DIR / ("mitmproxy-ca-cert.pem" if path.endswith("pem") else "mitmproxy-ca-cert.cer")
            if p.exists():
                flow.response = http.Response.make(200, p.read_bytes(), {
                    "Content-Type": "application/x-x509-ca-cert",
                    "Content-Disposition": f'attachment; filename="shoji-ca{p.suffix}"'})
            else:
                flow.response = http.Response.make(404, b"certificate not generated yet")
        else:
            flow.response = http.Response.make(200, "Shoji は動作中です".encode("utf-8"),
                                               {"Content-Type": "text/plain; charset=utf-8"})

    def _allow_site(self, flow: http.HTTPFlow, req: http.Request) -> None:
        """「このサイトでは止める」の確認画面（GET）と、その画面のボタンからの実行（POST）"""
        if req.method == "GET":
            qs = parse_qs(urlsplit(req.pretty_url).query)
            host = qs.get("host", [""])[0].lower().strip(".")
            ret = qs.get("return", [""])[0]
            if not re.fullmatch(r"[a-z0-9.-]+\.[a-z0-9-]+", host or ""):
                flow.response = http.Response.make(400, b"bad host", {"Content-Type": "text/plain"})
                return
            if not ret.startswith(("http://", "https://")):
                ret = f"https://{host}/"
            page = injector.allow_site_html(host, ret, self.ctx.issue_token("allow-site", host))
            # CORS ヘッダーは付けない（他のページがこの画面を読んでトークンを取り出せないように）
            flow.response = http.Response.make(200, page.encode("utf-8"), {
                "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",   # form-action はリダイレクト先まで制限するので付けない
                "X-Frame-Options": "DENY"})
            return
        form = parse_qs(req.get_text(strict=False) or "")
        host = form.get("host", [""])[0].lower()
        ret = form.get("return", [""])[0]
        mode = form.get("mode", [""])[0]
        if (req.headers.get("origin", "") != MAGIC_ORIGIN
                or not self.ctx.use_token(form.get("t", [""])[0], "allow-site", host)):
            flow.response = http.Response.make(403, b"forbidden", {"Content-Type": "text/plain"})
            return
        if mode == "always":
            wl = list(self.ctx.cfg.get("whitelist", []))
            if host not in wl:
                self.ctx.config.update({"whitelist": wl + [host]})
        else:
            self.ctx.allow_temporarily(host)
        self.ctx.reqlog.add(reqlog.ALLOWED, f"https://{host}/", host, page=host,
                            detail=t("log.site_allowed_always" if mode == "always" else "log.site_allowed_temp"))
        if not (ret.startswith(("http://", "https://")) and (_host_of(ret) == host or _host_of(ret).endswith("." + host))):
            ret = f"https://{host}/"
        flow.response = http.Response.make(303, b"", {"Location": ret, "Cache-Control": "no-store"})

    _picker_times: list = []

    def _picker_rule(self, req: http.Request) -> tuple[bool, dict]:
        """要素の選択ブロックから送られた「このサイトで隠す」ルールを保存する。
        どのページからでも呼べる窓口なので、受け付けるのは送信元サイト自身の要素を隠すルールだけにする
        （他サイトへの影響や、ブロックを無効にする例外ルールは受け付けない）。"""
        try:
            rule = str(json.loads(req.get_text(strict=False) or "{}").get("rule", "")).strip()
        except ValueError:
            return False, {"ok": False, "error": t("picker.bad")}
        origin_host = _host_of(req.headers.get("origin", "")) or _host_of(req.headers.get("referer", ""))
        m = re.match(r"^([a-z0-9.-]+)##(.+)$", rule)
        if not m or not origin_host:
            return False, {"ok": False, "error": t("picker.format")}
        domain, sel = m.group(1), m.group(2)
        if "." not in domain or not (origin_host == domain or origin_host.endswith("." + domain)):
            return False, {"ok": False, "error": t("picker.site")}
        if (len(sel) > 500 or sel.startswith(("+js", "^")) or any(c in sel for c in "{}\n\r")
                or "</" in sel or _PROCEDURAL_MARK.search(sel)):
            return False, {"ok": False, "error": t("picker.selector")}
        now = time.time()
        self._picker_times[:] = [t for t in self._picker_times if now - t < 60][-30:]
        if len(self._picker_times) >= 30:
            return False, {"ok": False, "error": t("picker.rate")}
        self._picker_times.append(now)
        added = lists.add_user_rule(rule, comment=t("picker.comment", time=time.strftime('%Y-%m-%d %H:%M')))
        if added:
            threading.Thread(target=lists.load_engine, args=(self.ctx,), daemon=True).start()
            self.ctx.reqlog.add(reqlog.MODIFIED, f"https://{origin_host}/", origin_host, page=origin_host,
                                rule=rule, detail=t("log.picker"))
        return True, {"ok": True, "added": added, "rule": rule}

    def _page_report(self, req: http.Request) -> None:
        try:
            data = json.loads(req.get_text(strict=False) or "{}")
        except ValueError:
            return
        host = str(data.get("host", ""))[:200]
        counts = data.get("counts") or {}
        details = counts.get("_d") or []
        for kind, n in counts.items():
            if kind not in _PAGE_REPORT_KINDS or not isinstance(n, int) or n <= 0 or n > 10000:
                continue
            rtype = _PAGE_REPORT_KINDS[kind]
            detail = next((d.split(":", 1)[1] for d in details if isinstance(d, str) and d.startswith(kind + ":")), "")
            self.ctx.stats.record(kind, "page", host, rtype or "other", count=n,
                                  count_bytes=rtype is not None, detail=detail)
