# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""見た目が有名なサイトにそっくりな、偽のドメインを見分ける。

フィッシング（偽のログイン画面）は、本物と見分けにくいドメインを使う。例:
- 別の文字体系のそっくりな文字: аpple.com（「а」はキリル文字）、ｇｏｏｇｌｅ.com（全角）
- 数字や文字の組み合わせ: paypa1.com（1 と l）、rnicrosoft.com（rn と m）、g00gle.com
ドメインの文字を「見た目が同じ基本の文字」に置き換え、有名なサイトのドメインと一致するのに
実際は別のドメインなら、偽物の可能性が高い。対象は、よく狙われる有名なサイトだけに絞る（誤検知を避けるため）。
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Optional

from .filters import registrable_domain

# よくフィッシングに使われる有名なサイト（登録されたドメイン単位）
BRANDS = frozenset({
    # 海外
    "apple.com", "icloud.com", "google.com", "gmail.com", "youtube.com", "microsoft.com", "live.com",
    "outlook.com", "office.com", "microsoftonline.com", "amazon.com", "paypal.com", "facebook.com",
    "instagram.com", "whatsapp.com", "netflix.com", "twitter.com", "linkedin.com", "github.com",
    "dropbox.com", "adobe.com", "yahoo.com", "ebay.com", "spotify.com", "discord.com", "steamcommunity.com",
    "steampowered.com", "epicgames.com", "binance.com", "coinbase.com", "kraken.com", "metamask.io",
    "chase.com", "bankofamerica.com", "wellsfargo.com", "americanexpress.com", "visa.com", "mastercard.com",
    "dhl.com", "fedex.com", "ups.com", "usps.com", "booking.com", "airbnb.com", "openai.com", "chatgpt.com",
    "claude.ai", "anthropic.com", "cloudflare.com", "okta.com", "docusign.com", "zoom.us", "wise.com",
    "stripe.com", "shopify.com", "walmart.com", "roblox.com", "tiktok.com", "telegram.org",
    # 日本
    "amazon.co.jp", "yahoo.co.jp", "rakuten.co.jp", "rakuten-card.co.jp", "rakuten-bank.co.jp",
    "rakuten-sec.co.jp", "docomo.ne.jp", "au.com", "softbank.jp", "mufg.jp", "smbc.co.jp", "smbc-card.com",
    "mizuhobank.co.jp", "japanpost.jp", "aeon.co.jp", "aeonbank.co.jp", "jcb.co.jp", "saisoncard.co.jp",
    "mercari.com", "paypay.ne.jp", "paypay-bank.co.jp", "line.me", "nta.go.jp", "sagawa-exp.co.jp",
    "kuronekoyamato.co.jp", "sbisec.co.jp", "nomura.co.jp", "monex.co.jp", "bitflyer.com", "coincheck.com",
    "bitbank.cc", "nintendo.com", "nintendo.co.jp", "playstation.com", "eki-net.com", "smartex.jp",
    "netbk.co.jp", "sonybank.net", "resonabank.co.jp", "jp-bank.japanpost.jp", "tepco.co.jp", "eposcard.co.jp",
})

# 見た目がラテン文字とほぼ同じ文字（キリル文字・ギリシャ文字など）。Unicode の confusables から主なものを選んだ
_CONFUSABLE = str.maketrans({
    # キリル文字
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w", "ӏ": "l", "ʟ": "l", "к": "k", "м": "m", "т": "t", "в": "b",
    "н": "h", "п": "n", "г": "r", "ү": "y", "ɡ": "g", "ɑ": "a", "ɩ": "i", "ɪ": "i",
    # ギリシャ文字
    "α": "a", "ο": "o", "ν": "v", "ρ": "p", "κ": "k", "ι": "i", "ε": "e", "τ": "t", "υ": "u", "χ": "x",
    "ω": "w", "β": "b", "η": "n", "μ": "u", "ϲ": "c", "ј": "j",
    # その他のラテン文字
    "ı": "i", "ȷ": "j", "ł": "l", "ø": "o", "đ": "d", "ħ": "h", "ŀ": "l", "ß": "ss", "æ": "ae",
})
# ASCII どうしの見間違い（文字の組み合わせ、数字と文字）。1・l・i は互いに見間違えやすいので同じ文字として扱う
_ASCII_SWAPS = (("rn", "m"), ("vv", "w"), ("0", "o"), ("1", "|"), ("l", "|"), ("i", "|"))


def _to_unicode(host: str) -> str:
    out = []
    for label in host.split("."):
        if label.startswith("xn--"):
            try:
                label = label[4:].encode("ascii").decode("punycode")
            except (UnicodeError, ValueError):
                pass
        out.append(label)
    return ".".join(out)


def skeleton(domain: str) -> str:
    """見た目の上での「骨組み」。全角・アクセント・別の文字体系のそっくりな文字を基本の文字にそろえる"""
    s = unicodedata.normalize("NFKC", domain).lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.translate(_CONFUSABLE)
    for a, b in _ASCII_SWAPS:
        s = s.replace(a, b)
    return s


_BRAND_BY_SKELETON = {skeleton(b): b for b in BRANDS}


@lru_cache(maxsize=8192)
def imitated_brand(host: str) -> Optional[str]:
    """host が有名なサイトに似せた別のドメインなら、その有名なサイトのドメインを返す"""
    host = (host or "").lower().rstrip(".")
    if not host or "." not in host:
        return None
    reg = registrable_domain(host)
    if reg in BRANDS:
        return None
    uni = _to_unicode(reg)
    brand = _BRAND_BY_SKELETON.get(skeleton(uni))
    if brand and brand != reg:
        return brand
    return None


def display(host: str) -> str:
    """警告画面に出す表記（xn-- を元の文字に戻したもの）"""
    return _to_unicode(host)
