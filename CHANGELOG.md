# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Optional annoyance lists (off by default): AdGuard Cookie Notices, Popups, Mobile App Banners, Widgets,
  Social Media and Other Annoyances. Turning one on downloads it right away. Their domains are blocked only
  inside web pages, never system-wide via DNS. Lists added in new versions now appear in existing setups.
- Filtering log (dashboard tab): the last 3,000 requests and DNS blocks with the action taken, the matching
  rule, the page they came from and the response status, filterable and searchable, with one-click
  Allow / Block buttons that add an editable user rule. Kept in memory only, never written to disk.
- Scriptlet support: uBlock Origin-style `##+js(...)` rules, about 30 scriptlets and their aliases
  (`set-constant`, `abort-on-property-read/write`, `abort-current-script`, `json-prune`, `no-fetch-if`,
  `no-xhr-if`, `no-setTimeout-if`, `addEventListener-defuser`, `no-window-open-if`, `remove-attr`,
  `remove-class`, `remove-node-text`, `href-sanitizer`, `set-cookie`, `set-local-storage-item`, …),
  with `#@#+js(...)` exceptions and `example.*` domains. Written independently for Shoji (Apache-2.0);
  `trusted-*` scriptlets are not supported. Can be turned off in the dashboard.
- Element-hiding rules for `example.*` (any TLD) domains now apply.

### Changed
- Built-in list of sites that are never decrypted, now covering major banks, brokers, payment services and
  password managers in Japan, the US, the UK, Europe and Australia. It always applies; the dashboard list is
  for your own additions.

## [0.2.0] - 2026-10-18

### Added
- Windows executable (`Shoji.exe`, no Python needed), built and attached to each GitHub Release automatically,
  with `LICENSE`, `NOTICE` and `THIRD_PARTY_LICENSES.txt` included.
- System tray icon: open dashboard, pause/resume, start with Windows, open log, quit.
- "Start with Windows" (per-user, no admin rights), also toggleable from the dashboard.
- Pause button on the dashboard.
- Single-instance guard: starting Shoji twice just opens the dashboard.
- Log file (`shoji.log`) in the data folder.
- `start_console.bat` for running with a visible console.
- `docs/LICENSING.md` explaining how the Apache License 2.0 and bundled third-party licenses apply.

### Changed
- The Windows proxy setting now uses a PAC script (`/proxy.pac`) by default, so browsers fall back to a direct
  connection automatically if Shoji stops. Set `proxy.system_proxy_mode` to `"static"` for the old behaviour.
- A watchdog process restores the original proxy/DNS settings if Shoji exits unexpectedly.
- `start.bat` starts Shoji in the tray without a console window.
- The Windows app keeps its data in `%LOCALAPPDATA%\Shoji` (`SHOJI_DATA` overrides). Custom rules now live in the data folder.

## [0.1.0] - 2026-10-18

First public release, formerly developed privately as `koukoku_blocker`.

### Added
- HTTPS filtering proxy (mitmproxy addon) with an Adblock Plus / uBlock Origin / AdGuard compatible filter engine.
- DNS filter with DNS-over-HTTPS upstream, caching and CNAME-cloaking detection.
- YouTube video ad removal (player-response pruning, feed ad cards, auto-skip fallback).
- Cosmetic filtering with on-demand generic selectors, space collapsing and re-inserted ad removal.
- Pop-up / pop-under / click-hijack overlay blocking.
- Optional hiding of self-hosted affiliate banners.
- Stealth mode: tracking-parameter stripping, referrer trimming, tracker cookie blocking, DNT/GPC,
  Client Hints and X-Client-Data removal, WebRTC leak protection, fingerprinting resistance.
- AMP redirection.
- Dashboard with statistics, charts, CSV export, settings, allow-list and custom rules.
- Windows integration: system proxy on/off with restore, DNS setup scripts, per-PC root certificate
  ("Shoji Local Filtering CA"), automatic Firefox configuration, per-application pass-through for apps
  that pin certificates.
