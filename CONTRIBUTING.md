# Contributing to Shoji

Thanks for helping. Issues and pull requests are welcome in English or Japanese (日本語でも歓迎します).

## Reporting problems

- **A site breaks or shows ads:** include the URL, your browser, and what you expected. You can use
  the dashboard's *Filters → URL check* to see which rule matched a request.
- **Shoji crashes or won't start:** include the console output of `start.bat` and your Windows / Python versions.
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

## Filter rules

Shoji downloads community filter lists at runtime. If a problem is in one of those lists, please report it
upstream (EasyList, AdGuard, uBlock Origin) so that every blocker benefits. Rules specific to Shoji's
behaviour belong in `rules/builtin_ads.txt` / `rules/builtin_trackers.txt`.
