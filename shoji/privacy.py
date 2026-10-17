# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""ステルスモード: 追跡パラメーター・リファラー・Cookie・ヘッダー情報の除去、AMP 無効化。"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from .filters import host_suffixes, is_third_party, registrable_domain

# どのサイトでも追跡目的でしか使われないパラメーター
TRACKING_PARAMS = {
    "fbclid", "gclid", "gclsrc", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "ysclid",
    "twclid", "ttclid", "li_fat_id", "igshid", "igsh", "mc_cid", "mc_eid", "_ga", "_gl",
    "_hsenc", "_hsmi", "__hssc", "__hstc", "__hsfp", "hsctatracking", "mkt_tok", "oly_anon_id",
    "oly_enc_id", "_openstat", "rb_clickid", "s_kwcid", "ef_id", "zanpid", "irclickid", "epik",
    "_branch_match_id", "srsltid", "gad_source", "gad_campaignid", "vero_id", "vero_conv",
    "wickedid", "__twitter_impression", "ldtag_cl", "ncid", "sr_share", "cvid", "obOrigUrl",
    "trk", "trkcampaign", "_bta_tid", "_bta_c", "spm", "scm", "mbid", "s_cid", "rcm", "fb_action_ids",
    "fb_action_types", "fb_ref", "fb_source", "action_object_map", "action_type_map",
    "action_ref_map",
}
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_", "stm_", "matomo_", "piwik_", "itm_")

# 特定サイトでのみ追跡に使われるパラメーター
SITE_PARAMS = {
    "amazon.": {"pd_rd_w", "pd_rd_wg", "pd_rd_r", "pd_rd_i", "pf_rd_p", "pf_rd_r", "pf_rd_s",
                "pf_rd_t", "pf_rd_i", "pf_rd_m", "_encoding", "crid", "sprefix", "qid", "sr",
                "dib", "dib_tag", "content-id", "linkcode", "ref_"},
    "youtube.com": {"si", "pp", "feature"},
    "youtu.be": {"si", "feature"},
    "x.com": {"s", "t", "ref_src", "ref_url"},
    "twitter.com": {"s", "t", "ref_src", "ref_url"},
    "instagram.com": {"utm_source", "igsh", "img_index"},
    "facebook.com": {"mibextid", "rdid", "sfnsn", "__tn__", "__cft__"},
    "rakuten.co.jp": {"scid", "sclid", "icm_acid", "icm_agid", "icm_cid", "l-id", "s-id"},
    "shopping.yahoo.co.jp": {"sc_e", "sc_i", "ea", "sc_pe"},
    "news.yahoo.co.jp": {"source"},
    "spotify.com": {"si", "context", "nd"},
    "tiktok.com": {"_r", "_t", "is_from_webapp", "sender_device", "is_copy_url"},
    "linkedin.com": {"trackingid", "refid", "lipi", "trk"},
    "reddit.com": {"share_id", "ref_source", "ref"},
    "aliexpress.": {"aff_platform", "aff_trace_key", "algo_expid", "algo_pvid", "btsid", "ws_ab_test"},
}
# 検索結果ページそのもので必要なパラメーター（除去しない）
_KEEP_ON = {
    "google.": {"ei", "ved", "oq", "aqs", "sourceid", "sxsrf", "gs_l", "uact", "sei"},
    "bing.com": {"cvid"},
}

SEARCH_ENGINES = ("google.", "bing.com", "search.yahoo.co.jp", "search.yahoo.com",
                  "duckduckgo.com", "yandex.", "baidu.com", "search.brave.com", "ecosia.org",
                  "startpage.com", "goo.ne.jp", "search.goo.ne.jp", "search.nifty.com")

# 高エントロピーな Client Hints（OS バージョン・機種・正確なブラウザバージョン等）
CLIENT_HINT_HEADERS = ("sec-ch-ua-full-version-list", "sec-ch-ua-full-version",
                       "sec-ch-ua-platform-version", "sec-ch-ua-model", "sec-ch-ua-arch",
                       "sec-ch-ua-bitness", "sec-ch-ua-wow64", "sec-ch-ua-form-factors",
                       "sec-ch-device-memory", "device-memory", "sec-ch-dpr", "dpr",
                       "sec-ch-viewport-width", "viewport-width", "sec-ch-width", "width",
                       "sec-ch-prefers-color-scheme", "sec-ch-prefers-reduced-motion", "rtt",
                       "downlink", "ect")


def _host_has(host: str, key: str) -> bool:
    if key.endswith("."):
        return any(s.startswith(key) for s in host_suffixes(host))
    return host == key or host.endswith("." + key)


def strip_tracking_params(url: str, extra: Optional[list[str]] = None,
                          generic: bool = True) -> tuple[str, list[str]]:
    """URL から追跡パラメーターを除去する。(新 URL, 除去したパラメーター名) を返す。
    generic=False のときはフィルタリストの $removeparam だけを使う（署名付き URL を壊さないため、
    ページ遷移以外の通信には内蔵リストを適用しない）"""
    parts = urlsplit(url)
    if not parts.query:
        return url, []
    host = (parts.hostname or "").lower()
    site = set()
    for k, v in SITE_PARAMS.items():
        if _host_has(host, k):
            site |= v
    keep = set()
    for k, v in _KEEP_ON.items():
        if _host_has(host, k):
            keep |= v
    extra_exact, extra_rx, remove_all = set(), [], False
    for e in extra or []:
        if e == "":
            remove_all = True
        elif e.startswith("/") and e.endswith("/") and len(e) > 2:
            try:
                extra_rx.append(re.compile(e[1:-1]))
            except re.error:
                pass
        elif e.startswith("~"):
            continue
        else:
            extra_exact.add(e.lower())
    removed, kept = [], []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        kl = k.lower()
        drop = False
        if kl not in keep:
            if ((generic and (kl in TRACKING_PARAMS or kl.startswith(TRACKING_PREFIXES) or kl in site))
                    or kl in extra_exact or remove_all
                    or any(rx.search(f"{k}={v}") for rx in extra_rx)):
                drop = True
        (removed if drop else kept).append((k, v) if not drop else k)
    if not removed:
        return url, []
    query = urlencode(kept, doseq=True, quote_via=quote, safe="/:@!$'()*,;")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment)), removed


def is_search_engine(host: str) -> bool:
    return any(_host_has(host, s) for s in SEARCH_ENGINES)


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}/" if p.scheme and p.netloc else ""


def generic_user_agent(ua: str) -> str:
    """OS・ブラウザの詳細を伏せた汎用 UA（メジャーバージョンだけ維持）"""
    m = re.search(r"(Chrome|Edg|Firefox)/(\d+)", ua or "")
    if m and m.group(1) == "Firefox":
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{m.group(2)}.0) Gecko/20100101 Firefox/{m.group(2)}.0"
    major = m.group(2) if m else "130"
    edge = f" Edg/{major}.0.0.0" if "Edg/" in (ua or "") else ""
    return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36{edge}")


def limit_cookie_age(set_cookie: str, max_seconds: int) -> str:
    """Set-Cookie の寿命を max_seconds までに制限する"""
    s = re.sub(r";\s*expires=[^;]*", "", set_cookie, flags=re.I)
    m = re.search(r";\s*max-age=(-?\d+)", s, flags=re.I)
    if m:
        if int(m.group(1)) > max_seconds:
            s = s[:m.start()] + f"; Max-Age={max_seconds}" + s[m.end():]
        return s
    # Expires のみで永続化していた Cookie は寿命を付与（セッション Cookie はそのまま）
    if re.search(r";\s*expires=", set_cookie, flags=re.I):
        s += f"; Max-Age={max_seconds}"
    return s


# --------------------------------------------------------------------------
# AMP
# --------------------------------------------------------------------------
_AMP_GOOGLE = re.compile(r"^https?://(?:www\.)?google\.[a-z.]+/amp/(?:s/)?(.+)$", re.I)
_AMP_CACHE = re.compile(r"^https?://[^/]+\.cdn\.ampproject\.org/[a-z]/(s/)?(.+)$", re.I)
_AMP_CANON = re.compile(r"<link\b[^>]*\brel=[\"']?canonical[\"']?[^>]*>", re.I)
_HREF = re.compile(r"\bhref=[\"']([^\"']+)[\"']", re.I)
_IS_AMP_HTML = re.compile(r"<html\b[^>]*\s(?:amp|⚡)(?:[\s=>])", re.I)


def amp_redirect_url(url: str) -> Optional[str]:
    """Google AMP ビューア / AMP キャッシュの URL なら元ページの URL を返す"""
    m = _AMP_GOOGLE.match(url)
    if m:
        target = unquote(m.group(1))
        return target if target.startswith("http") else "https://" + target
    m = _AMP_CACHE.match(url)
    if m:
        return ("https://" if m.group(1) else "http://") + m.group(2)
    return None


def amp_canonical(html_head: str, current_url: str) -> Optional[str]:
    """AMP ページの HTML なら canonical URL を返す"""
    if not _IS_AMP_HTML.search(html_head[:4000]):
        return None
    m = _AMP_CANON.search(html_head)
    if not m:
        return None
    h = _HREF.search(m.group(0))
    if not h:
        return None
    canon = h.group(1).replace("&amp;", "&")
    if canon.startswith("//"):
        canon = urlsplit(current_url).scheme + ":" + canon
    if not canon.startswith("http") or canon.rstrip("/") == current_url.rstrip("/"):
        return None
    return canon


__all__ = ["strip_tracking_params", "is_search_engine", "origin_of", "generic_user_agent",
           "limit_cookie_age", "amp_redirect_url", "amp_canonical", "CLIENT_HINT_HEADERS",
           "is_third_party", "registrable_domain"]
