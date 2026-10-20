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
| **Scriptlets** | Runs uBlock Origin-style `##+js(...)` rules (≈3k in the default lists) to defuse anti-adblock walls and ad scripts: `set-constant`, `abort-on-property-read`, `json-prune`, `no-fetch-if`, `no-setTimeout-if`, `remove-attr` and about 25 more. Shoji's own implementation, no uBO code. |
| **Extended CSS** | Site-specific rules that plain CSS can't express: `:has-text()`, `:upward()`, `:xpath()`, `:matches-css()`, `:remove()`, `:style()` and more, plus AdGuard `#?#` / `#$#` and Adblock Plus `:-abp-has()` syntax (≈2k rules in the default lists). |
| **Script stand-ins** | When an ad or analytics script is blocked, Shoji can return a harmless stand-in instead (`$redirect`), so pages that call Google Analytics, Tag Manager, AdSense, GPT or the IMA video-ad SDK keep working. Shoji's own implementations. |
| **Re-inserted ads** | A MutationObserver removes ads that scripts insert or force back into view. |
| **Pop-ups** | Blocks pop-ups and pop-unders opened without a real click, script-generated new-tab tricks, and invisible click-hijacking overlays. |
| **Affiliate banners** | Optionally hides banner images that a site hosts itself and wraps in affiliate links (`rel="sponsored"`, Amazon, Rakuten, A8, …). |
| **Stealth mode** | Strips tracking parameters (`utm_*`, `fbclid`, `gclid`, …), hides your search terms from destination sites, trims referrers, blocks tracker cookies, sends DNT/GPC, removes high-entropy Client Hints and `X-Client-Data`, prevents WebRTC IP leaks and resists screen/hardware/canvas fingerprinting. |
| **AMP off** | Redirects Google AMP viewer/cache URLs and AMP pages to the publisher's normal page. |
| **Dangerous sites & scams** | Warns before opening known malware, phishing and cryptomining sites (URLhaus, phishing and NoCoin lists), and defuses tech-support-scam pages that lock the screen with endless alerts, full screen and back-button traps. |
| **Annoyances** | Optional AdGuard lists that hide cookie notices, in-page pop-ups, chat widgets, app banners and social buttons (off by default). |
| **Element picker** | Press `Ctrl`+`Shift`+`Alt`+`H` on any page, click the thing you want gone, and Shoji saves a "hide this on this site" rule. |
| **Turn off on a site** | If a site breaks, press `Ctrl`+`Shift`+`Alt`+`P` to turn Shoji off there for an hour or always, or allow a recently opened site from the dashboard with one click. |
| **Filtering log** | A live list of recent requests and what Shoji did with each (blocked, passed, modified, not decrypted, page fixes), with the matching rule and one-click **Allow / Block** that writes a user rule. Kept in memory only. |
| **Japanese / English** | The whole interface is available in both languages and follows the Windows display language by default. |
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

## Install

### Windows app (recommended — no Python needed)

1. Download **`Shoji-<version>-windows-x64.zip`** from the [latest release](../../releases/latest) and unzip it anywhere.
2. Run **`Shoji.exe`**. A shōji icon appears in the system tray and the dashboard opens at <http://127.0.0.1:8765>.

The executable is not code-signed yet, so Windows SmartScreen may say *"Windows protected your PC"*.
Click **More info → Run anyway**. You can verify the download with the `.sha256` file on the release page.

### From source (Windows 10/11, [Python 3.12+](https://www.python.org/downloads/))

```bat
git clone https://github.com/ebipepe/shoji.git
cd shoji
install.bat
start.bat
```

`start.bat` runs Shoji in the tray without a console window. Use `start_console.bat` to see the log while debugging.

## Use

1. On first run Windows asks whether to trust **"Shoji Local Filtering CA (this PC only)"**. Choose **Yes**,
   then restart your browser.
2. Right-click the **tray icon** to pause filtering, open the dashboard, turn on **"Start with Windows"**, or quit.
3. *(Optional, for in-app ads)* Right-click **`set_dns.bat` → Run as administrator** to point Windows DNS at Shoji.
   Undo it with `reset_dns.bat`.

Shoji points Windows at itself with a **proxy auto-config (PAC) script**: if Shoji stops or crashes,
browsers fall back to a direct connection automatically, so you never lose internet access. A small watchdog
also restores your original settings if Shoji exits unexpectedly (`restore_network.bat` remains as a last resort).
Settings, statistics and logs live in `data\` (source) or `%LOCALAPPDATA%\Shoji` (Windows app).

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
- A few rarely used rule types are skipped when lists are loaded: HTML filters (`##^`), AdGuard JavaScript rules (`#%#`),
  `:others()` and procedural rules meant for every site.
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
See [docs/LICENSING.md](docs/LICENSING.md) for what this means for contributors and redistributors,
and how the Windows executable handles bundled third-party licenses.
