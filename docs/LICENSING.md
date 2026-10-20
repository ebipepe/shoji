# Licensing

Shoji is licensed under the [Apache License, Version 2.0](../LICENSE).
This page explains what that means in practice for users, contributors and redistributors, and how the
Windows executable handles the licenses of the libraries it bundles. It is a summary, not legal advice;
the license texts are what count.

## For users

You may use Shoji for any purpose, personal or commercial, free of charge. There is no warranty (§7–8 of the license).

## For contributors

- Contributions are accepted under the Apache License 2.0 (§5 "inbound = outbound"); no separate CLA is required.
- Copyright stays with each contributor. The project-wide notice is "Copyright 2026 The Shoji Authors",
  and contributors may add themselves to [AUTHORS](../AUTHORS).
- Every source file starts with an SPDX header:
  ```
  # SPDX-License-Identifier: Apache-2.0
  # Copyright 2026 The Shoji Authors
  ```
- Only submit code you wrote yourself or that is under an Apache-2.0-compatible license (MIT, BSD, Apache-2.0, ISC…).
  Do not copy code or rules from GPL-licensed projects (for example uBlock Origin or EasyList) into this repository.

## For redistributors and forks (§4 of the license)

If you redistribute Shoji, modified or not, in source or binary form, you must:

1. Include a copy of [LICENSE](../LICENSE).
2. Include the [NOTICE](../NOTICE) file (you may add your own notices to it, but not remove ours).
3. Keep the existing copyright, patent, trademark and attribution notices in the source files.
4. Mark modified files with a prominent notice that you changed them.
5. For binary builds, also ship the third-party license texts (`THIRD_PARTY_LICENSES.txt`, see below).

**Name and logo (§6):** the license does not grant rights to the name "Shoji" or its icon. Forks that
change the behaviour should use a different name so users are not confused, while saying that they are
based on Shoji.

## Third-party components

### Source distribution
The repository contains no third-party code. `install.bat` installs the dependencies listed in
`requirements.txt` from PyPI under their own licenses.

### Windows executable
`Shoji.exe` is built with PyInstaller and bundles Python and the dependencies. The release workflow
(`.github/workflows/release.yml`) generates `THIRD_PARTY_LICENSES.txt` with the full license and NOTICE
texts of exactly the packages installed in the build environment, and ships it next to the executable
together with `LICENSE` and `NOTICE`.

| Component | License | How it is handled |
|---|---|---|
| Python runtime | PSF License | License text included |
| mitmproxy and most dependencies | MIT / BSD / Apache-2.0 | License texts included |
| certifi | MPL-2.0 | Unmodified; source link in NOTICE |
| pystray, ldap3 | LGPL-3.0 | Shipped as plain, unmodified `.py` files (not inside the archive) so users can inspect and replace them |
| urwid (mitmproxy console UI) | LGPL-2.1 | Not used; excluded from the build |
| WinDivert / pydivert (mitmproxy transparent mode) | LGPL-3.0 | Not used; excluded from the build (a small stub replaces the module that would import it) |
| PyInstaller bootloader | GPL-2.0 with bootloader exception | The exception allows distributing the bundled program under any license |

The exclusions and the LGPL handling are configured in [`packaging/shoji.spec`](../packaging/shoji.spec).
When adding a dependency, check its license; avoid GPL/AGPL libraries, and mirror the LGPL handling above
if an LGPL library is unavoidable.

### Filter lists
EasyList, AdGuard, uBlock Origin and other lists are **downloaded at runtime from their maintainers and are
not part of this repository or the executable**. They remain under their own licenses (mostly GPLv3 or
CC BY-SA), are used unmodified, and are credited in NOTICE. Shoji's built-in rules in `rules/` are original
to this project and licensed under Apache-2.0.

### Scriptlets
The lists use uBlock Origin's `##+js(...)` syntax to call small in-page functions ("scriptlets"). uBlock
Origin's and AdGuard's own scriptlet code is GPL-3.0, so Shoji does **not** reuse it:
[`shoji/assets/scriptlets.js`](../shoji/assets/scriptlets.js) is an independent implementation written from
the documented behaviour of each scriptlet (name and arguments), under Apache-2.0. Please keep it that way —
don't paste code from those projects into it.

The same applies to the **extended CSS engine** ([`shoji/procedural.py`](../shoji/procedural.py),
[`shoji/assets/procedural.js`](../shoji/assets/procedural.js)) and the **`$redirect` stand-ins**
([`shoji/assets/redirects/`](../shoji/assets/redirects/)): they are written from the documented filter syntax and
the public APIs of the libraries they stand in for, not from uBlock Origin's or AdGuard's resources. The tiny
silent MP3/MP4 files were generated for this project with FFmpeg.

---

## 日本語の要約

- **使う人:** 個人・商用を問わず無料で使えます。無保証です。
- **貢献する人:** 送ってもらったコードは Apache License 2.0 で受け入れます（別途の同意書は不要）。著作権は各自に残ります。GPL のプロジェクト（uBlock Origin、EasyList など）のコードやルールをこのリポジトリにコピーしないでください。
- **再配布する人:** LICENSE と NOTICE を同梱し、ソースの著作権表示を残し、変更したファイルには変更した旨を書いてください。exe を配る場合は `THIRD_PARTY_LICENSES.txt` も同梱します。
- **名前とアイコン:** ライセンスは「Shoji」の名前やアイコンの使用権を与えません。動作を変えた派生版は別の名前にしてください（「Shoji をもとにしている」と書くのは問題ありません）。
- **exe の同梱物:** 同梱ライブラリのライセンス全文を自動で生成して同梱しています。LGPL のライブラリ（pystray、ldap3）は差し替え可能な .py ファイルのまま同梱し、使っていない LGPL 部分（urwid、WinDivert）は除外しています。
- **フィルタリスト:** 実行時に配布元からダウンロードするだけで、リポジトリにも exe にも含めていません。
