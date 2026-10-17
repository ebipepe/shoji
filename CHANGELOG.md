# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

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
