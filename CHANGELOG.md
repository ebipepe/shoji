# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **ClickFix protection.** Pages that secretly copy a dangerous command (PowerShell, mshta, `cmd /c`, …) to the
  clipboard and tell you to paste it into the Run box ("I'm not a robot", "press Win+R") are stopped: the clipboard
  gets a harmless notice instead and a warning is shown. Commands shown on the page with a copy button
  (documentation sites) and your own Ctrl+C are not affected.
- **Browser update check.** Shoji tells you on the dashboard when the Edge, Chrome or Firefox you use is older than
  the latest version, checked once a day from the vendors' public version information (can be turned off). Only the
  major version can be compared, because browsers no longer send the full version.

### Changed
- Much lower memory use. With the default and annoyance lists (about 850,000 network rules), Shoji used about
  1.3 GB; it now uses about 0.5 GB, and loading the lists takes about half as long. Rules that only name a host
  (`||example.com^`, about half of all rules) are stored as a plain host table, and identical option sets are
  shared. Matching results are unchanged (checked against the previous engine on 216,000 requests).

## [0.5.4] - 2026-10-28

### Added
- Source version: Shoji checks at startup that the installed packages are not older than `requirements-lock.txt`
  and shows a warning in the log and on the dashboard. `start.bat` asks you to run `install.bat` when an update
  changed the package versions (`git pull` alone does not update `.venv`).

### Changed
- `install.bat` installs the same pinned, hash-checked versions as the Windows app (falling back to
  `requirements.txt` if they cannot be installed), and stops if Shoji is running, because Windows locks the files
  of a running Shoji and the update fails ("Access is denied").

### Fixed
- Microsoft Store and winget (`mp.microsoft.com`, `winget.microsoft.com`, `winget.azureedge.net`) are no longer
  decrypted. They check the certificate after connecting, so `winget upgrade` failed with 0x8a15005e while Shoji
  was running.
- `THIRD_PARTY_LICENSES.txt` now also lists `wcwidth`, which is installed with mitmproxy's urwid. pip-licenses hides
  it by default because it uses the package itself. It is not part of `Shoji.exe`, so earlier releases were not
  missing a required license; it is listed for completeness. (The v0.5.3 notes said this was already fixed; it was not.)

## [0.5.3] - 2026-10-28

### Security
- Updated the bundled Brotli decoder to 1.2.1 (with mitmproxy 12.3.1). Brotli 1.0.3–1.2.0 has an out-of-bounds
  write when decoding a crafted compressed stream (critical; GitHub advisory "Node2Shell"). Shoji decodes
  Brotli-compressed web pages to filter them, so please update. Running from source now requires mitmproxy 12.3.1
  or later.

### Changed
- The Windows release is now built from pinned versions with hashes (`requirements-lock.txt`), so third-party
  packages change only when they are deliberately updated. See *Dependencies* in CONTRIBUTING.md.

## [0.5.2] - 2026-10-24

### Added
- X (Twitter) promoted posts are removed from timelines, replies and search. Shoji drops the entries that X marks
  as promoted in the data the page receives, so it works whatever the label says ("Ad", "広告", "Promoted").
- "Remove Shoji from this PC" (Setup tab): one click undoes the changes Shoji made to Windows (Start with Windows,
  proxy, DNS, the Firefox setting, the root certificate), then shows which folders to delete and offers to quit.
- Privacy policy (`docs/PRIVACY.md`), code signing policy (`docs/CODE_SIGNING.md`) and uninstall instructions in
  the README.

### Fixed
- Restoring the proxy a second time (for example "Turn system proxy off" and then quitting) no longer clears a
  proxy you had configured before Shoji, such as a company proxy.
- Removing the certificate now targets Shoji's own certificate by its fingerprint, so it can never remove a
  different certificate with a similar name.

## [0.5.1] - 2026-10-23

### Changed
- The dashboard's summary cards fit on one row on a normal-width window, and tables scroll inside their card on
  narrow screens instead of making the whole page scroll sideways.
- README: screenshots (before/after comparison, dashboard, filtering log, element picker, warning pages).

### Fixed
- Shoji's own block pages and stand-in scripts no longer get the page script injected into them.

### Security
- Dangerous-site blocking (malware, phishing, cryptomining lists) can no longer be lifted by exception rules
  in ad or tracker lists, including `$document` page exceptions. Only your own rules, the allowlist or the
  security lists themselves can lift it.
- Domain-only lists (Peter Lowe's list, AdGuard DNS filter) now contribute only domain-level rules. Element
  hiding, scriptlets, URL patterns and options such as `$document` or `$badfilter` in them are ignored, so a
  tampered copy cannot reach beyond blocking domains.
- Downloaded filter lists are checked before use: an error page instead of a list, an empty list, a file that is
  too large, or a list that suddenly shrinks to less than half its previous size is not used. The previous copy
  stays in use and the Filters tab shows why. "Update now" imports the new copy without the shrink check.

## [0.5.0] - 2026-10-20

### Added
- Extended CSS (procedural cosmetic filters) for site-specific rules: `:has-text()` / `:contains()`, `:has()` /
  `:not()` with procedural arguments, `:upward()` / `:nth-ancestor()`, `:xpath()`, `:matches-css()` (incl. `before`
  / `after`), `:min-text-length()`, `:matches-attr()`, `:matches-path()`, `:watch-attr()`, and the actions
  `:remove()`, `:style()`, `:remove-attr()`, `:remove-class()`. AdGuard `#?#`, `#$#` (CSS injection, incl.
  `remove: true`) and `[-ext-…]` syntax and Adblock Plus `:-abp-has()` / `:-abp-contains()` / `:-abp-properties()`
  are understood too. About 2,000 rules in the default lists that used to be skipped now work.
- `$redirect` and `$redirect-rule`: blocked requests can be answered with a harmless stand-in (empty script, text,
  transparent image, silent audio/video, empty VAST/VMAP, or stand-ins for Google Analytics, Tag Manager,
  AdSense, Google Publisher Tag, the IMA video-ad SDK, FingerprintJS, FuckAdBlock, Amazon apstag and others).
  The most common Google ad/analytics scripts get a stand-in automatically when blocked, even without a
  `$redirect` rule. Blocked images are answered with a transparent image instead of an error.

### Changed
- Stealth mode: the "maximum lifetime of first-party cookies" setting now has an explanation of what it does.

### Fixed
- `@@…$redirect` exception rules no longer allow the request; they only turn off the stand-in.
  `$redirect-rule` filters no longer block on their own.
- A few statistics details and messages (cookie blocking, YouTube ads, CNAME cloaking, DNS start errors) were
  always in Japanese; they now follow the display language.

## [0.4.1] - 2026-10-20

### Added
- "Turn Shoji off on this site": press `Ctrl`+`Shift`+`Alt`+`P` on a page to open a Shoji confirmation page where you
  can turn filtering off on that site for an hour or always (adds it to the allowlist). The dashboard's
  Allowlist tab also lists recently opened sites with a one-click "Allow" button. Dangerous-site blocking
  still applies to third-party requests on allowlisted sites.
- The log file (`shoji.log`) and console messages now follow the display language too.

### Security
- The "open anyway" link on block pages and the new site-off page now require a one-time token issued by
  Shoji's own page, so other web pages can no longer allow themselves or other hosts by calling
  `https://shoji.blocker/...` directly.

### Changed
- Keyboard shortcuts are now `Ctrl`+`Shift`+`Alt`+`H` (element picker) and `Ctrl`+`Shift`+`Alt`+`P` (turn off on
  this site). `Alt`+`Shift`+letter clashes with Chrome/Edge shortcuts and with page access keys in Firefox.
  Shortcuts are ignored while typing in a text field, and both can be changed or disabled in the dashboard
  (Setup → Keyboard shortcuts).
- Pages that Shoji modified are sent with `Cache-Control: no-store`, so turning a site off or changing rules
  is not hidden by a cached, already-filtered copy.

## [0.4.0] - 2026-10-20

### Added
- Element picker: press `Alt`+`Shift`+`H` on a page, click what you want gone, adjust with
  "wider / narrower" or edit the selector, and save it as a site-specific hiding rule. The rule applies
  immediately. The picker's save endpoint only accepts element-hiding rules for the page's own site.
- Dangerous-site protection (on by default, "block_malware"): Malicious URL Blocklist (URLhaus), Phishing URL
  Blocklist and NoCoin lists, blocked in browsers and via DNS, with a dedicated warning page that lets you go
  back or proceed for an hour.
- Tech-support-scam guard: pages that combine scam wording (virus warnings, support phone numbers) with
  screen-locking behaviour (alert floods, full screen, keyboard/pointer lock, history flooding,
  beforeunload traps) are defused and covered with a warning. More than five dialogs in 30 seconds are
  suppressed on any page.
- English user interface. The dashboard, tray menu, block and warning pages, element picker, scam warning,
  filtering-log details and filter-list descriptions are available in Japanese and English. The language
  follows the Windows display language by default and can be changed in the dashboard (top right, or Setup).
  The log file (`shoji.log`) is still in Japanese.

### Changed
- The dashboard's "block rate" tile is now "share of traffic that was ads/trackers", with the blocked count and
  an explanation, so it is not mistaken for how many ads were caught.
- Pages are always fetched fresh (no 304 revalidation) while HTTPS filtering is on, so new rules apply on
  reload instead of a cached copy with the old ones.
- Filter lists can have mirror URLs; if the main download fails, the mirrors are tried (NoCoin now falls back
  to jsDelivr).

## [0.3.0] - 2026-10-19

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

### Fixed
- The dashboard no longer writes every status request to `shoji.log`.
- Toggle switches in the filter list table were squashed.

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
