# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
#
# PyInstaller spec for the Windows build of Shoji.
#   pyinstaller packaging/shoji.spec --noconfirm
# Produces dist/Shoji/Shoji.exe (one-folder build: starts fast and is less likely
# to trip antivirus heuristics than a one-file build).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

ROOT = Path(SPECPATH).parent
IS_WIN = sys.platform == "win32"

# Not needed by Shoji, and kept out of the binary so that no (L)GPL code is linked in:
#   urwid / mitmproxy.tools.console  - mitmproxy's interactive terminal UI (LGPL-2.1)
#   pydivert / mitmproxy_windows     - WinDivert, only for mitmproxy's transparent / "local" modes (LGPL-3.0)
#   mitmproxy.platform.windows       - imports pydivert; replaced by a stub (rthook_no_windivert.py)
EXCLUDED = ["urwid", "mitmproxy.tools.console", "pydivert", "mitmproxy_windows", "mitmproxy.platform.windows",
            "tkinter", "matplotlib", "numpy", "pytest"]


def _wanted(mod: str) -> bool:
    return not any(mod == e or mod.startswith(e + ".") for e in EXCLUDED)


hidden = []
hidden += [m for m in collect_submodules("mitmproxy") if _wanted(m)]   # addons are imported dynamically
hidden += collect_submodules("shoji")
hidden += ["dnslib", "flask", "werkzeug"]
if IS_WIN:
    hidden += ["pystray._win32"]

datas = []
datas += [(str(ROOT / "shoji" / "assets"), "shoji/assets")]
datas += [(str(ROOT / "rules"), "rules")]
datas += [(str(ROOT / f), ".") for f in ("LICENSE", "NOTICE", "README.md", "README.ja.md", "SECURITY.md")]
if (ROOT / "THIRD_PARTY_LICENSES.txt").exists():
    datas += [(str(ROOT / "THIRD_PARTY_LICENSES.txt"), ".")]
datas += collect_data_files("mitmproxy")
datas += copy_metadata("mitmproxy")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    hiddenimports=hidden,
    datas=datas,
    excludes=EXCLUDED,
    runtime_hooks=[str(ROOT / "packaging" / "rthook_no_windivert.py")],
    # LGPL-licensed libraries are shipped as plain .py files (not inside the archive) so that
    # users can inspect and replace them, as the LGPL requires.
    module_collection_mode={"ldap3": "py", "pystray": "py"},
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Shoji",
    icon=str(ROOT / "assets" / "icon" / "shoji.ico"),
    console=False,              # runs in the system tray; logs go to %LOCALAPPDATA%\Shoji\shoji.log
)
coll = COLLECT(exe, a.binaries, a.datas, name="Shoji")
