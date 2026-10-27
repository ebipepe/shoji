# Contributing to Shoji

Thanks for helping. Issues and pull requests are welcome in English or Japanese (日本語でも歓迎します).

## Reporting problems

- **A site breaks or shows ads:** include the URL, your browser, and what you expected. You can use
  the dashboard's *Filters → URL check* to see which rule matched a request.
- **Shoji crashes or won't start:** attach `shoji.log` (tray menu → *Open log*; it is in `%LOCALAPPDATA%\Shoji` for the Windows app or `data\` for the source version) and your Windows version.
- **Security issues:** see [SECURITY.md](SECURITY.md). Please don't file them publicly.

## Development setup

```bat
git clone https://github.com/ebipepe/shoji.git
cd shoji
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyflakes
python tests/test_core.py
python main.py --no-system-proxy --no-dns   # run without touching system settings
```

The core (filter engine, YouTube pruning, CSP handling, privacy helpers) is platform-independent, so you
can develop and test it on Linux/macOS too. Only `shoji/winsys.py` is Windows-specific.

## Pull requests

- Keep changes focused; one topic per PR.
- Add or update a test in `tests/` when you change filtering behaviour.
- Run `python -m pyflakes shoji main.py tests` and `python tests/test_core.py` before pushing.
  CI runs the same checks on Windows and Linux.
- Every new source file starts with the license header:

  ```python
  # SPDX-License-Identifier: Apache-2.0
  # Copyright 2026 The Shoji Authors
  ```

- By submitting a contribution you agree that it is licensed under the Apache License 2.0
  (see section 5 of [LICENSE](LICENSE)). Feel free to add yourself to [AUTHORS](AUTHORS).

## Dependencies

`requirements.txt` lists the packages Shoji needs with minimum versions; running from source installs the newest
ones. The Windows release build instead installs **exact versions with hashes** from `requirements-lock.txt`
(and `packaging/build-lock.txt` / `packaging/licenses-lock.txt` for PyInstaller and pip-licenses), so a release
never picks up a new third-party version by surprise.

When you add, remove or update a package, regenerate the lists with [uv](https://docs.astral.sh/uv/) and commit
them together with `requirements.txt`:

```bat
pip install uv
rem After editing requirements.txt (keeps the other versions):
python packaging/update_locks.py
rem Update one package:
python packaging/update_locks.py -P mitmproxy
rem Update everything:
python packaging/update_locks.py --upgrade
```

Quit Shoji before running `install.bat` or `pip install` on the source version: Windows locks the files of a running
Shoji (for example `_brotli.cp312-win_amd64.pyd`) and pip fails with "Access is denied". `install.bat` checks this.

`python tests/test_core.py` fails if `requirements-lock.txt` is missing a package from `requirements.txt`, and a
pull request that changes these files runs a trial Windows build. Security fixes in bundled packages are released
promptly; other updates are usually batched with a regular release.

## Filter rules

Shoji downloads community filter lists at runtime. If a problem is in one of those lists, please report it
upstream (EasyList, AdGuard, uBlock Origin) so that every blocker benefits. Rules specific to Shoji's
behaviour belong in `rules/builtin_ads.txt` / `rules/builtin_trackers.txt`.
