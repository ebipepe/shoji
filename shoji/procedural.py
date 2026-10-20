# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""拡張 CSS（手続き型の要素非表示ルール）の解析。

ブラウザの CSS だけでは書けないルールを、ページ内スクリプト（assets/procedural.js）が
順に実行できる「手順」に変換する。対応する書き方:

  uBlock Origin 形式  example.com##div:has-text(広告)  / :upward(2) / :xpath(...) / :remove() / :style(...)
  AdGuard 形式        example.com#?#div:contains(広告)  / :nth-ancestor(2) / [-ext-has="..."]
                      example.com#$#.banner { display: none !important; }   （CSS の差し込み）
  Adblock Plus 形式   example.com#?#div:-abp-has(.ad) / :-abp-contains(...) / :-abp-properties(...)

手順は JSON にできる dict:
  {"s": 先頭の CSS セレクタ（None なら起点そのもの）,
   "o": [[操作名, 引数...], ...],
   "a": [動作, 引数...]   （"hide" / "remove" / "style" / "rmattr" / "rmclass"）,
   "p": [パスの正規表現, フラグ]   （:matches-path、省略可）}
正規表現は JavaScript の RegExp にそのまま渡せる [ソース, フラグ] の形で持つ。
"""
from __future__ import annotations

import re
from typing import Optional

# 手続き型の操作名（ブラウザの CSS には無いもの）
_OPS = ("-abp-has", "-abp-contains", "-abp-properties", "has-text", "contains", "has", "if-not", "if",
        "not", "upward", "nth-ancestor", "xpath", "matches-css-before", "matches-css-after",
        "matches-css", "min-text-length", "matches-path", "matches-attr", "watch-attr",
        "remove-attr", "remove-class", "remove", "style", "others", "matches-prop", "shadow")
_OP_RE = re.compile(r":(" + "|".join(re.escape(o) for o in _OPS) + r")\(")
# 中身がブラウザの CSS だけなら、ブラウザに任せてよい操作
_NATIVE_IF_PLAIN = {"has", "not"}
_ACTIONS = {"remove", "style", "remove-attr", "remove-class"}
_UNSUPPORTED = {"others", "matches-prop", "shadow"}
# AdGuard の属性形式 [-ext-has="..."] など
_EXT_ATTR_RE = re.compile(r"\[-ext-([a-z-]+)=([\"'])((?:\\.|(?!\2).)*)\2\]")
_COMBINATOR_START = re.compile(r"^\s*[>+~]|^\s+\S")
# :style() で受け付けない記述（外部の読み込み・スクリプト実行・ルールの書き換え）
_UNSAFE_STYLE = re.compile(r"url\s*\(|image-set|expression|javascript:|@import|[{}<>\\]|/\*", re.I)

MAX_DEPTH = 6


class Unsupported(ValueError):
    pass


def is_procedural(body: str) -> bool:
    """ブラウザの CSS だけでは扱えない記述を含むか"""
    if _EXT_ATTR_RE.search(body):
        return True
    for m in _OP_RE.finditer(body):
        name = m.group(1)
        if name not in _NATIVE_IF_PLAIN:
            return True
        arg, _ = _read_paren(body, m.end() - 1)
        if arg is None or is_procedural(arg) or _starts_with_combinator(arg) and name == "not":
            return True
        if name == "has" and ":has(" in arg:
            return True   # :has() の中の :has() はブラウザの CSS では無効
    return False


def _starts_with_combinator(s: str) -> bool:
    return bool(re.match(r"^\s*[>+~]", s))


def _read_paren(s: str, open_idx: int) -> tuple[Optional[str], int]:
    """s[open_idx] == '(' から対応する ')' までの中身と、閉じ括弧の位置"""
    depth, i, quote, n = 0, open_idx, "", len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if quote:
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1:i], i
        i += 1
    return None, -1


def _split(sel: str) -> list[tuple[str, str]]:
    """セレクタを [("css", 文字列) | (操作名, 引数)] に分ける"""
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    i, n = 0, len(sel)
    bracket, paren, quote = 0, 0, ""
    while i < n:
        c = sel[i]
        if c == "\\":
            buf.append(sel[i:i + 2])
            i += 2
            continue
        if quote:
            buf.append(c)
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "\"'" and (bracket or paren):
            quote = c
        elif c == "[":
            bracket += 1
        elif c == "]":
            bracket = max(0, bracket - 1)
        elif c == ":" and not bracket and not paren:
            m = _OP_RE.match(sel, i)
            if m:
                name = m.group(1)
                arg, close = _read_paren(sel, m.end() - 1)
                if arg is None:
                    raise Unsupported("unbalanced")
                native = name in _NATIVE_IF_PLAIN and not is_procedural(arg) and not (
                    name == "not" and _starts_with_combinator(arg)) and not (name == "has" and ":has(" in arg)
                if not native:
                    if buf:
                        out.append(("css", "".join(buf)))
                        buf = []
                    out.append((name, arg))
                    i = close + 1
                    continue
        elif c == "(" and not bracket:
            paren += 1
        elif c == ")" and not bracket:
            paren = max(0, paren - 1)
        buf.append(c)
        i += 1
    if buf:
        out.append(("css", "".join(buf)))
    return out


def _compound_end(css: str) -> int:
    """先頭の複合セレクタ（結合子の手前まで）の長さ"""
    bracket = paren = 0
    quote = ""
    i = 0
    while i < len(css):
        c = css[i]
        if c == "\\":
            i += 2
            continue
        if quote:
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "[":
            bracket += 1
        elif c == "]":
            bracket -= 1
        elif c == "(":
            paren += 1
        elif c == ")":
            paren -= 1
        elif not bracket and not paren and (c.isspace() or c in ">+~"):
            return i
        i += 1
    return len(css)


def _ends_open(css: str) -> bool:
    """'div ' や 'a >' のように、後ろに要素の指定が続く形で終わっているか"""
    return bool(css) and (css[-1].isspace() or css.rstrip()[-1:] in (">", "+", "~"))


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


_JS_SPECIAL = set("\\^$.*+?()[]{}|/-")


def _escape(s: str) -> str:
    return "".join("\\" + c if c in _JS_SPECIAL else c for c in s)


def text_pattern(arg: str, *, wildcard: bool = False, exact: bool = False) -> list:
    """/正規表現/フラグ か文字列を [ソース, フラグ] にする"""
    a = _unquote(arg)
    m = re.match(r"^/(.+)/([imsu]*)$", a, re.S)
    if m:
        # 正規表現の文法は JavaScript 側で確認する（無効なら、その手順だけ使わない）
        src, flags = m.group(1), m.group(2).replace("u", "")
        if len(src) > 2000:
            raise Unsupported("regex too long")
        return [src, flags]
    if wildcard:
        src = ".*".join(_escape(p) for p in a.split("*"))
        return ["^" + src + "$", ""]
    if exact:
        return ["^" + _escape(a) + "$", ""]
    return [_escape(a), ""]


def _css_prop_pattern(arg: str) -> list:
    """matches-css の引数 'prop: value' （AdGuard の 'before, prop: value' も）"""
    a = _unquote(arg)
    pseudo = ""
    m = re.match(r"^\s*(before|after)\s*,\s*(.*)$", a, re.S)
    if m:
        pseudo, a = "::" + m.group(1), m.group(2)
    prop, sep, val = a.partition(":")
    prop = prop.strip().lower()
    if not sep or not re.match(r"^-?[a-z][a-z0-9-]*$", prop):
        raise Unsupported("matches-css")
    return [prop, text_pattern(val.strip(), wildcard=True), pseudo]


def _int_arg(arg: str, lo: int, hi: int) -> Optional[int]:
    a = arg.strip()
    if re.fullmatch(r"\d+", a):
        v = int(a)
        if lo <= v <= hi:
            return v
        raise Unsupported("out of range")
    return None


def _style_decls(decl: str) -> list:
    """'color: red; display: none !important' -> [["color","red"],["display","none"]]"""
    if _UNSAFE_STYLE.search(decl):
        raise Unsupported("unsafe style")
    out = []
    for part in decl.split(";"):
        part = part.strip()
        if not part:
            continue
        prop, sep, val = part.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        val = re.sub(r"\s*!\s*important\s*$", "", val, flags=re.I)
        if not sep or not re.fullmatch(r"(?:--|-)?[a-z][a-z0-9-]*", prop) or not val:
            raise Unsupported("bad style")
        out.append([prop, val])
    if not out:
        raise Unsupported("empty style")
    return out


def _ext_attrs(sel: str) -> str:
    """AdGuard の [-ext-name="value"] を :name(value) にする"""
    return _EXT_ATTR_RE.sub(lambda m: f":{m.group(1)}({m.group(3)})", sel)


def parse(sel: str, *, relative: bool = False, depth: int = 0) -> dict:
    """セレクタを手順にする。対応できない書き方なら Unsupported"""
    if depth > MAX_DEPTH:
        raise Unsupported("too deep")
    sel = _ext_attrs(sel.strip() if not relative else sel)
    if not sel.strip():
        raise Unsupported("empty")
    segs = _split(sel)
    path = None
    rest = []
    for kind, arg in segs:
        if kind == "matches-path":
            if depth:
                raise Unsupported("nested matches-path")
            path = text_pattern(arg)
        else:
            rest.append((kind, arg))
    segs = rest
    if path and segs and segs[0][0] == "css":
        segs[0] = ("css", segs[0][1].lstrip())
        if not segs[0][1]:
            segs.pop(0)

    task: dict = {"s": None, "o": []}
    if path:
        task["p"] = path
    ops = task["o"]
    action = None
    first = True
    for idx, (kind, arg) in enumerate(segs):
        if action is not None:
            raise Unsupported("operator after action")
        if kind == "css":
            css = arg
            if idx + 1 < len(segs) and _ends_open(css):
                # 'div :has-text(x)' / 'a > :has-text(x)' -> 任意の要素
                css = css.rstrip() + ("*" if css.rstrip()[-1:] in (">", "+", "~") else " *")
            if first:
                if relative:
                    # :has(> .a) / :has(.a) のような起点からの相対指定
                    task["s"] = None
                    ops.append(["spath", css.rstrip() if _COMBINATOR_START.match(css) else " " + css.strip()])
                else:
                    task["s"] = css.strip()
            elif _COMBINATOR_START.match(css):
                ops.append(["spath", css.rstrip()])
            else:
                # ':not(.a) + .b' -> 自分自身の絞り込み ':not(.a)' と、そこからの相対指定 ' + .b'
                end = _compound_end(css)
                ops.append(["match", css[:end].strip()])
                if css[end:].strip():
                    ops.append(["spath", css[end:].rstrip()])
            first = False
            continue
        if first:
            # 先頭が操作だけ（例: ##:xpath(...) / :has(:has-text(...))）
            if kind == "xpath" or relative:
                # :has(:has-text(x)) / :not(:has-text(x)) は、要素そのものに対して調べる
                task["s"] = None
            else:
                task["s"] = "*"
            first = False
        if kind in _UNSUPPORTED:
            raise Unsupported(kind)
        if kind in ("has-text", "contains", "-abp-contains"):
            ops.append(["text", text_pattern(arg)])
        elif kind in ("has", "-abp-has", "if"):
            ops.append(["has", parse(arg, relative=True, depth=depth + 1)])
        elif kind in ("not", "if-not"):
            ops.append(["not", parse(arg, relative=True, depth=depth + 1)])
        elif kind in ("upward", "nth-ancestor"):
            v = _int_arg(arg, 1, 256)
            if v is None:
                if kind == "nth-ancestor":
                    raise Unsupported("nth-ancestor")
                s = arg.strip()
                if not s or is_procedural(s):
                    raise Unsupported("upward")
                ops.append(["up", s])
            else:
                ops.append(["up", v])
        elif kind == "xpath":
            x = _unquote(arg)
            if not x:
                raise Unsupported("xpath")
            ops.append(["xpath", x])
        elif kind in ("matches-css", "matches-css-before", "matches-css-after"):
            prop, pat, pseudo = _css_prop_pattern(arg)
            if kind != "matches-css":
                pseudo = "::" + kind.rsplit("-", 1)[1]
            ops.append(["css", prop, pat, pseudo])
        elif kind == "-abp-properties":
            for part in _unquote(arg).split(";"):
                if part.strip():
                    prop, pat, pseudo = _css_prop_pattern(part)
                    ops.append(["css", prop, pat, pseudo])
        elif kind == "min-text-length":
            v = _int_arg(arg, 0, 1_000_000)
            if v is None:
                raise Unsupported("min-text-length")
            ops.append(["minlen", v])
        elif kind == "matches-attr":
            name, sep, val = arg.partition("=")
            ops.append(["attr", text_pattern(name, exact=True),
                        text_pattern(val, exact=True) if sep else None])
        elif kind == "watch-attr":
            names = [n.strip() for n in _unquote(arg).split(",") if n.strip()]
            ops.append(["watch", names])
        elif kind == "remove":
            if arg.strip():
                raise Unsupported("remove arg")
            action = ["remove"]
        elif kind == "style":
            action = ["style", _style_decls(arg)]
        elif kind == "remove-attr":
            action = ["rmattr", text_pattern(arg, exact=True)]
        elif kind == "remove-class":
            action = ["rmclass", text_pattern(arg, exact=True)]
        else:
            raise Unsupported(kind)
    if task["s"] is not None and not task["s"]:
        task["s"] = "*"
    if action and depth:
        raise Unsupported("nested action")
    if action:
        task["a"] = action
    return task


def parse_css_injection(body: str) -> tuple[str, dict]:
    """AdGuard の #$# 'selector { declarations }' を (セレクタ, 手順) にする"""
    m = re.match(r"^(.+?)\s*\{(.*)\}\s*$", body, re.S)
    if not m:
        raise Unsupported("css injection")
    sel, decl = m.group(1).strip(), m.group(2).strip()
    if sel.startswith("@") or not sel:
        raise Unsupported("at-rule")
    if re.fullmatch(r"remove\s*:\s*true\s*;?", decl, re.I):
        task = parse(sel + ":remove()")
    elif re.fullmatch(r"display\s*:\s*none\s*(!\s*important)?\s*;?", decl, re.I):
        task = parse(sel)
    else:
        task = parse(sel)
        if task.get("a"):
            raise Unsupported("action in injection")
        task["a"] = ["style", _style_decls(decl)]
    return sel, task


def plain_css_rule(task: dict) -> Optional[str]:
    """操作の無い :style() は、ページ内スクリプトを使わず CSS として差し込める"""
    if task.get("o") or task.get("p") or not task.get("s"):
        return None
    a = task.get("a")
    if not a or a[0] != "style":
        return None
    decls = ";".join(f"{p}:{v}!important" for p, v in a[1])
    return f"{task['s']}{{{decls}}}"
