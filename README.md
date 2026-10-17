<p align="center">
  <img src="assets/icon/png/shoji-128.png" width="96" height="96" alt="Shoji icon">
</p>

<h1 align="center">Shoji</h1>

<p align="center">
  <b>A local ad, tracker and privacy filter for Windows.</b><br>
  Like a <i>shōji</i> paper screen, it lets the light in and keeps prying eyes out.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <img alt="Platform: Windows" src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-informational">
  <img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-informational">
  <img alt="Status: early" src="https://img.shields.io/badge/status-early%20(0.1)-orange">
</p>

<p align="center"><a href="README.ja.md">日本語</a></p>

---

Shoji runs on your own PC as an **HTTPS filtering proxy**, a **DNS filter** and a **local dashboard**.
It blocks ads and trackers in every browser and in apps that respect the system proxy, removes
YouTube video ads, and strips the data that analytics systems use to follow you around the web.
Everything happens on your machine. Nothing is sent to any Shoji server, because there isn't one.

> **Status:** early release (0.1). It is in daily use on Windows 11 with Microsoft Edge, but expect rough edges.
> Please [open an issue](../../issues) when something breaks.

## Features

| | |
|---|---|
| **Ad blocking** | Network-level blocking with EasyList, AdGuard (incl. Japanese), uBlock Origin filters and more (≈650k rules). Blocked requests never leave your PC, so pages load faster and use less data. |
| **YouTube video ads** | Removes the ad schedule from YouTube's player responses (the same approach as uBlock Origin's `json-prune`), drops ad cards from feeds and search, and auto-skips anything that slips through. |
| **Tracker blocking** | EasyPrivacy / AdGuard Tracking Protection at URL and DNS level, plus **CNAME-cloaking** detection. |
| **App ads** | A built-in DNS server (DNS-over-HTTPS upstream) blocks ad and tracker domains for every app, and for phones on your LAN if you point them at it. |
| **Cosmetic filtering** | Hides ad slots with ~56k element-hiding rules, then **collapses the empty space** they leave behind. |
| **Re-inserted ads** | A MutationObserver removes ads that scripts insert or force back into view. |
| **Pop-ups** | Blocks pop-ups and pop-unders opened without a real click, script-generated new-tab tricks, and invisible click-hijacking overlays. |
| **Affiliate banners** | Optionally hides banner images that a site hosts itself and wraps in affiliate links (`rel="sponsored"`, Amazon, Rakuten, A8, …). |
| **Stealth mode** | Strips tracking parameters (`utm_*`, `fbclid`, `gclid`, …), hides your search terms from destination sites, trims referrers, blocks tracker cookies, sends DNT/GPC, removes high-entropy Client Hints and `X-Client-Data`, prevents WebRTC IP leaks and resists screen/hardware/canvas fingerprinting. |
| **AMP off** | Redirects Google AMP viewer/cache URLs and AMP pages to the publisher's normal page. |
| **Statistics** | Ads, trackers, pop-ups and video ads blocked; estimated data and time saved; top domains; hourly/daily charts; CSV export. |

## How it works

```
 Browser / apps ──► Shoji proxy (mitmproxy, 127.0.0.1:8080) ──► Internet
                     │  • block ad/tracker URLs (filter engine)
                     │  • prune YouTube ad data, strip tracking params & headers
                     │  • inject a small page script + hide-CSS into HTML
                     │
 Any app's DNS ───► Shoji DNS (127.0.0.1:53) ──► DNS-over-HTTPS upstream
                     • answers 0.0.0.0 for ad/tracker domains

 Dashboard: http://127.0.0.1:8765  (statistics, settings, allow-list, custom rules)
```

HTTPS filtering works by generating a **root certificate unique to your PC** and adding it to
Windows' trust store, so the proxy can read and filter encrypted traffic locally. Apps that pin their
certificates (Slack, ChatGPT, Discord, …) are detected automatically and passed through untouched.
Read [SECURITY.md](SECURITY.md) before using it.

## Requirements

- Windows 10 or 11
- [Python 3.12+](https://www.python.org/downloads/) (tick **"Add python.exe to PATH"** during setup)

## Install

```bat
git clone https://github.com/ebipepe/shoji.git
cd shoji
install.bat
```

Or download the ZIP from the [Releases](../../releases) page and run `install.bat`.

## Use

1. Run **`start.bat`**. The dashboard opens at <http://127.0.0.1:8765>.
2. On first run Windows asks whether to trust **"Shoji Local Filtering CA (this PC only)"**. Choose **Yes**,
   then restart your browser.
3. *(Optional, for in-app ads)* Right-click **`set_dns.bat` → Run as administrator** to point Windows DNS at Shoji.
   Undo it with `reset_dns.bat`.

While Shoji runs, the Windows proxy setting points at it. Press `Ctrl+C` to stop and the original
settings are restored. If Shoji ever crashes and your connection breaks, run **`restore_network.bat`**.

Firefox keeps its own certificate store. Shoji turns on Firefox's *use Windows certificates*
setting automatically. Restart Firefox once after the first run.

### Phones and tablets

Set `dns.listen_host` and `proxy.listen_host` to `"0.0.0.0"` in `data\config.json`, restart Shoji, and set
your phone's Wi-Fi DNS to your PC's IP address. For HTTPS filtering as well, set the Wi-Fi proxy to
`<PC IP>:8080` and install the certificate from `http://shoji.blocker/cert`.

## Known limitations

- **YouTube's official mobile/TV apps** pin their certificates and serve ads from the same servers as
  videos, so neither DNS nor the proxy can remove those ads. YouTube in a browser is supported.
- Video sites that stitch ads into the video stream server-side (SSAI) can't be filtered.
- uBlock Origin scriptlets (`##+js(...)`) and some procedural cosmetic filters (`:has-text`, …) are not supported yet
  and are skipped when lists are loaded.
- Data/time-saved figures are **estimates** based on typical sizes of the blocked resource types.
- The filter engine is pure Python. It is fast enough for normal browsing (typically well under 1 ms per request),
  but slower than native blockers.

## Project layout

```
main.py                    entry point (proxy + DNS + dashboard + list updater)
shoji/filters.py           filter engine (Adblock Plus / uBO / AdGuard syntax, hosts files)
shoji/proxy_addon.py       HTTPS filtering (mitmproxy addon)
shoji/dns_server.py        DNS filter (DoH upstream, cache, CNAME uncloaking)
shoji/youtube.py           YouTube ad removal
shoji/privacy.py           stealth mode, AMP
shoji/injector.py          page script/CSS injection, CSP handling
shoji/assets/content.js    in-page script (pop-ups, re-insertion, space collapse, …)
shoji/dashboard.py         dashboard API; UI in shoji/assets/dashboard.html
shoji/stats.py             statistics (SQLite)
shoji/winsys.py            Windows proxy / DNS / certificate integration
rules/                     built-in and user rules
docs/                      development history and design notes
```

## Contributing

Bug reports, filter fixes and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
Security issues: please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Acknowledgements

Shoji stands on the shoulders of [mitmproxy](https://mitmproxy.org/), [dnslib](https://github.com/paulc/dnslib),
[Flask](https://flask.palletsprojects.com/) and, above all, the volunteers who maintain
[EasyList](https://easylist.to/), [AdGuard filters](https://github.com/AdguardTeam/AdguardFilters),
[uBlock Origin's uAssets](https://github.com/uBlockOrigin/uAssets) and [Peter Lowe's list](https://pgl.yoyo.org/adservers/).
Filter lists are downloaded from their maintainers at runtime and remain under their own licenses (see [NOTICE](NOTICE)).

## License

[Apache License 2.0](LICENSE). Copyright 2026 The Shoji Authors.
