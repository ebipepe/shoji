# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""HTML への要素非表示 CSS・ページ内スクリプトの埋め込みと CSP の調整。"""
from __future__ import annotations

import base64
import hashlib
import json
import re

from .config import ASSETS_DIR
from .filters import selectors_to_css

MAGIC_HOST = "shoji.blocker"
MAGIC_ORIGIN = f"https://{MAGIC_HOST}"



def _strip_comments(js: str) -> str:
    """行頭のコメントだけを除去する簡易ミニファイ（文字列中の // は触らない）"""
    js = re.sub(r"(?m)^\s*/\*.*?\*/\s*$", "", js, flags=re.S)
    js = re.sub(r"(?m)^\s*//.*$", "", js)
    return re.sub(r"\n\s*\n+", "\n", js)


def js_ascii(s: str) -> str:
    """どの文字コード (Shift_JIS 等) のページに埋め込んでも壊れないよう ASCII 化"""
    return "".join(c if ord(c) < 128 else
                   (f"\\u{ord(c):04x}" if ord(c) < 0x10000 else
                    "".join(f"\\u{u:04x}" for u in _utf16(c))) for c in s)


def css_ascii(s: str) -> str:
    return "".join(c if ord(c) < 128 else f"\\{ord(c):x} " for c in s)


def _utf16(c: str):
    b = c.encode("utf-16-be")
    return [int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b), 2)]


_CONTENT_JS = _strip_comments((ASSETS_DIR / "content.js").read_text(encoding="utf-8"))
_PLACEHOLDER = "window.__SHOJI_CFG__"

_HEAD_RE = re.compile(r"<head\b[^>]*>", re.I)
_META_CHARSET_RE = re.compile(r"<meta\b[^>]*charset[^>]*>", re.I)
_HTML_RE = re.compile(r"<html\b[^>]*>", re.I)
_NONCE_RE = re.compile(r"'nonce-([A-Za-z0-9+/=_\-]+)'")


def _sha256(s: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()


def build_snippet(cfg: dict, specific: list[str], exceptions: list[str], generic_inline: list[str],
                  use_generic: bool, version: str) -> tuple[str, str, str]:
    """(埋め込む HTML, script の CSP ハッシュ, style の CSP ハッシュ)"""
    parts = []
    if use_generic:
        parts.append(f'<link rel="stylesheet" crossorigin="anonymous" '
                     f'href="{MAGIC_ORIGIN}/generic-complex.css?v={version}">')
    sels = list(dict.fromkeys(specific + [g for g in generic_inline if g not in set(exceptions)]))
    css = selectors_to_css(sels) if sels else ""
    if exceptions:
        # サイト別の例外 (#@#) — 汎用ルールで隠れた要素を元に戻す
        css += "\n" + ",".join(exceptions) + "{display:revert!important}"
    # <style> は空でも必ず置く（後から CSSOM で汎用ルールを追加するため。CSSOM は CSP の制限を受けない）
    css = css_ascii(css.replace("</", "<\\/"))
    style_hash = _sha256(css)
    parts.append(f'<style id="shoji-css">{css}</style>')
    cfg_json = json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))
    cfg_json = cfg_json.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    js = js_ascii(_CONTENT_JS.replace(_PLACEHOLDER, cfg_json))
    script_hash = _sha256(js)
    parts.append(f"<script>{js}</script>")
    return "".join(parts), script_hash, style_hash


def inject(html: str, snippet: str) -> str:
    """<meta charset> の直後（無ければ <head> の直後）に挿入する"""
    head = _HEAD_RE.search(html, 0, 20000)
    if head:
        meta = _META_CHARSET_RE.search(html, head.end(), head.end() + 3000)
        pos = meta.end() if meta else head.end()
    else:
        h = _HTML_RE.search(html, 0, 20000)
        if h:
            pos = h.end()
        elif html.lstrip()[:15].lower().startswith("<!doctype"):
            pos = html.find(">") + 1
        else:
            pos = 0
    return html[:pos] + snippet + html[pos:]


def nonce_for(csp: str) -> str:
    m = _NONCE_RE.search(csp or "")
    return m.group(1) if m else ""


def _inline_allowed(tokens: list[str]) -> bool:
    """そのディレクティブがインラインの script/style を既に許可しているか"""
    if "'unsafe-inline'" not in tokens:
        return False
    # nonce / hash / strict-dynamic があると 'unsafe-inline' は無視される
    return not any(t.startswith(("'nonce-", "'sha256-", "'sha384-", "'sha512-")) or t == "'strict-dynamic'"
                   for t in tokens)


def _patch_policy(policy: str, script_hash: str, style_hash: str) -> str:
    directives: list[list] = []
    for d in policy.split(";"):
        d = d.strip()
        if d:
            name, _, val = d.partition(" ")
            directives.append([name.lower(), val.split()])
    names = {}
    for d in directives:
        names.setdefault(d[0], d)       # 同名ディレクティブは最初のものだけが有効

    def effective(*order):
        for n in order:
            if n in names:
                return names[n]
        return None

    def add(d, token):
        if "'none'" in d[1]:
            d[1].remove("'none'")
        if token not in d[1]:
            d[1].append(token)

    def ensure_source(kind_names: tuple, token: str, inline: bool):
        """kind_names 例: ("script-src-elem", "script-src", "default-src")"""
        eff = effective(*kind_names)
        if eff is None:
            return                                   # 制限なし
        if inline and _inline_allowed(eff[1]):
            return                                   # 既にインライン許可
        if not inline and ("*" in eff[1] or "https:" in eff[1]):
            return
        targets = [names[n] for n in kind_names[:-1] if n in names]
        if not targets:
            # default-src だけの場合は、それを元に専用ディレクティブを作る
            d = [kind_names[-2], list(eff[1])]
            directives.append(d)
            names[d[0]] = d
            targets = [d]
        for d in targets:
            add(d, token)

    if script_hash:
        ensure_source(("script-src-elem", "script-src", "default-src"), f"'{script_hash}'", True)
    if style_hash:
        ensure_source(("style-src-elem", "style-src", "default-src"), f"'{style_hash}'", True)
    ensure_source(("style-src-elem", "style-src", "default-src"), MAGIC_ORIGIN, False)
    ensure_source(("connect-src", "default-src"), MAGIC_ORIGIN, False)
    return ";".join((n + " " + " ".join(v)).strip() for n, v in directives)


def patch_csp(csp: str, script_hash: str, style_hash: str, nonce: str = "") -> str:
    """埋め込んだ script/style と shoji.blocker を許可するよう CSP を書き換える。
    1 つのヘッダーにカンマ区切りで複数のポリシーが入っている場合（YouTube 等）は、それぞれ個別に処理する。"""
    if not csp:
        return csp
    return ", ".join(_patch_policy(p, script_hash, style_hash) for p in csp.split(",") if p.strip())


def blocked_frame_html() -> str:
    """ブロックした iframe の中身: 親ページに枠を畳むよう伝える"""
    return ("<!doctype html><meta charset=utf-8><style>html,body{margin:0;background:transparent}</style>"
            "<script>try{parent.postMessage({shoji:'collapse'},'*')}catch(e){}</script>")


def blocked_page_html(url: str, host: str, category: str, rule: str) -> str:
    import html as _h
    label = "トラッカー" if category == "tracker" else "広告"
    allow = f"{MAGIC_ORIGIN}/allow?url=" + _url_quote(url)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ブロックしました</title>
<style>
:root{{color-scheme:light dark;--bg:#f6f7f9;--fg:#1d2330;--mut:#667085;--card:#fff;--acc:#2f6fed;--bd:#e3e6ec}}
@media (prefers-color-scheme:dark){{:root{{--bg:#12151b;--fg:#e8eaee;--mut:#98a2b3;--card:#1b2029;--bd:#2a313d}}}}
body{{margin:0;font:15px/1.7 system-ui,"Segoe UI","Hiragino Sans","Yu Gothic UI",sans-serif;background:var(--bg);color:var(--fg);display:grid;place-items:center;min-height:100vh}}
.c{{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:28px 32px;max-width:560px;margin:16px}}
h1{{font-size:20px;margin:0 0 8px}} p{{color:var(--mut);margin:6px 0}} code{{word-break:break-all;font-size:12px}}
.b{{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}}
a.btn{{padding:8px 16px;border-radius:8px;text-decoration:none;border:1px solid var(--bd);color:var(--fg)}}
a.pri{{background:var(--acc);color:#fff;border-color:var(--acc)}}
</style></head><body><div class="c">
<h1>{label}ページをブロックしました</h1>
<p><b>{_h.escape(host)}</b> は{label}配信先としてフィルタに登録されています。</p>
<p><code>{_h.escape(url[:300])}</code></p>
<p style="font-size:12px">ルール: <code>{_h.escape(rule[:200])}</code></p>
<div class="b"><a class="btn pri" href="javascript:history.back()">戻る</a>
<a class="btn" href="{_h.escape(allow)}">このまま開く（1時間許可）</a></div>
<p style="font-size:12px;margin-top:18px">Shoji</p></div>
<script>
// ポップアップ/新しいタブとして開かれた広告ならそのまま閉じる
if (window.opener || (history.length <= 1 && document.referrer)) {{
  try {{ navigator.sendBeacon('{MAGIC_ORIGIN}/report', JSON.stringify({{host: location.hostname, counts: {{popup: 1}}}})); }} catch (e) {{}}
  setTimeout(function () {{ window.close(); }}, 50);
}}
</script></body></html>"""


def _url_quote(u: str) -> str:
    from urllib.parse import quote
    return quote(u, safe="")
