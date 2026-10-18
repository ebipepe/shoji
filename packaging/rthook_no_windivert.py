# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
#
# PyInstaller runtime hook for the Windows build.
# On Windows, mitmproxy imports two WinDivert-based helpers (LGPL-3.0) at start-up:
#   mitmproxy.platform.windows  (transparent mode, needs pydivert)
#   mitmproxy_windows           (imported by mitmproxy_rs; ships windows-redirector.exe for "local" mode)
# Shoji runs mitmproxy only as a regular proxy and never uses those modes, so the executable ships
# these small stubs instead of WinDivert.
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

if sys.platform == "win32" and "mitmproxy_windows" not in sys.modules:
    _mw = types.ModuleType("mitmproxy_windows")

    def executable_path():
        raise RuntimeError("Local capture mode is not available in Shoji")

    _mw.executable_path = executable_path
    sys.modules["mitmproxy_windows"] = _mw
