# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
#
# PyInstaller runtime hook for the Windows build.
# mitmproxy imports its transparent-mode helper (mitmproxy.platform.windows) at start-up on Windows,
# and that module imports pydivert / WinDivert (LGPL-3.0). Shoji runs mitmproxy only as a regular
# proxy and never uses transparent mode, so the executable ships a stub instead of WinDivert.
import sys
import types

if sys.platform == "win32" and "mitmproxy.platform.windows" not in sys.modules:
    _stub = types.ModuleType("mitmproxy.platform.windows")

    class Resolver:
        def setup(self):
            raise RuntimeError("Transparent mode is not available in Shoji")

        def original_addr(self, csock):
            raise RuntimeError("Transparent mode is not available in Shoji")

    _stub.Resolver = Resolver
    sys.modules["mitmproxy.platform.windows"] = _stub
