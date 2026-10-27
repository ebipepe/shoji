# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""Regenerate the pinned dependency lists used by the Windows release build.

The release build installs exact versions with hashes, so a release never picks up a
new third-party version by surprise. This script rewrites those lists:

    requirements-lock.txt              everything bundled in Shoji.exe (from requirements.txt)
    packaging/build-lock.txt           PyInstaller, installed next to it only to build the exe
    packaging/licenses-lock.txt        pip-licenses, run in its own environment

Usage (needs uv: pip install uv):

    python packaging/update_locks.py                 keep the current versions; only add or
                                                     remove what changed in requirements.txt
    python packaging/update_locks.py -P mitmproxy    update one package (repeatable)
    python packaging/update_locks.py --upgrade       update everything to the newest versions

After updating, run the tests and a trial release build before publishing a release.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The release build runs on 64-bit Windows with this Python version (see release.yml)
TARGET = ["--python-platform", "x86_64-pc-windows-msvc", "--python-version", "3.12"]
COMMAND = "python packaging/update_locks.py"

# (output file, input requirements, constraint files)
LOCKS = [
    ("requirements-lock.txt", None, []),
    ("packaging/build-lock.txt", "pyinstaller\n", ["requirements-lock.txt"]),
    ("packaging/licenses-lock.txt", "pip-licenses\n", []),
]


def compile_lock(uv: str, out: str, text: str | None, constraints: list[str], extra: list[str]) -> None:
    cmd = [uv, "pip", "compile", "--quiet", "--generate-hashes", "--no-strip-markers",
           "--custom-compile-command", COMMAND, *TARGET, "-o", out]
    for c in constraints:
        cmd += ["-c", c]
    cmd += ["requirements.txt"] if text is None else ["-"]
    print("→", out)
    subprocess.run(cmd + extra, cwd=ROOT, input=text, text=True, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--upgrade", action="store_true", help="update every package to the newest version")
    ap.add_argument("-P", "--upgrade-package", action="append", default=[], metavar="NAME",
                    help="update one package (can be given more than once)")
    args = ap.parse_args()

    uv = shutil.which("uv")
    if not uv:
        print("uv was not found. Install it with: pip install uv", file=sys.stderr)
        return 1
    extra = ["--upgrade"] if args.upgrade else [x for p in args.upgrade_package for x in ("-P", p)]
    for out, text, constraints in LOCKS:
        compile_lock(uv, out, text, constraints, extra)
    print("Done. Run the tests and a trial release build before publishing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
