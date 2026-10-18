# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""タスクトレイ（通知領域）のアイコンとメニュー。Windows 専用。

pystray を使い、別スレッドで動かす（メインスレッドは mitmproxy のイベントループが使う）。
"""
from __future__ import annotations

import threading
import webbrowser
from typing import Callable

from . import winsys
from .config import ASSETS_DIR, LOG_PATH
from .context import AppContext


def _load_icon(paused: bool = False):
    from PIL import Image, ImageEnhance
    png = ASSETS_DIR / "icon-64.png"
    img = Image.open(png).convert("RGBA")
    if paused:
        # 一時停止中は色を薄くして見分けられるようにする
        img = ImageEnhance.Color(img).enhance(0.0)
        img = ImageEnhance.Brightness(img).enhance(1.15)
    return img


class Tray:
    def __init__(self, ctx: AppContext, dashboard_url: str, on_exit: Callable[[], None]):
        self.ctx = ctx
        self.url = dashboard_url
        self.on_exit = on_exit
        self.icon = None

    # ---------------------------------------------------------------- メニュー
    def _menu(self):
        import pystray
        Item = pystray.MenuItem
        return pystray.Menu(
            Item("ダッシュボードを開く", self._open_dashboard, default=True),
            Item(lambda _: "フィルタを再開" if self.ctx.paused else "フィルタを一時停止", self._toggle_pause),
            pystray.Menu.SEPARATOR,
            Item("Windows の起動時に開始", self._toggle_autostart,
                 checked=lambda _: winsys.get_autostart()),
            Item("ログを開く", lambda: winsys.open_path(LOG_PATH)),
            pystray.Menu.SEPARATOR,
            Item("Shoji を終了", self._exit),
        )

    def _open_dashboard(self, *_):
        webbrowser.open(self.url)

    def _toggle_pause(self, *_):
        self.ctx.set_paused(not self.ctx.paused)
        self.refresh()

    def _toggle_autostart(self, *_):
        winsys.set_autostart(not winsys.get_autostart())

    def _exit(self, *_):
        self.stop()
        self.on_exit()

    # ---------------------------------------------------------------- 表示
    def refresh(self):
        if not self.icon:
            return
        paused = self.ctx.paused
        self.icon.icon = _load_icon(paused)
        self.icon.title = "Shoji（一時停止中）" if paused else "Shoji — 広告・トラッカーをブロック中"
        self.icon.update_menu()

    def start(self) -> bool:
        try:
            import pystray
        except ImportError:
            print("[tray] pystray が見つからないため、タスクトレイには表示しません（pip install pystray pillow）")
            return False
        self.icon = pystray.Icon("Shoji", _load_icon(self.ctx.paused), "Shoji — 広告・トラッカーをブロック中",
                                 menu=self._menu())
        self.ctx.on_pause_change.append(lambda _p: self.refresh())
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
        return True

    def notify(self, message: str, title: str = "Shoji"):
        try:
            if self.icon:
                self.icon.notify(message, title)
        except Exception:  # noqa: BLE001 — 通知は失敗しても動作に影響させない
            pass

    def stop(self):
        try:
            if self.icon:
                self.icon.stop()
        except Exception:  # noqa: BLE001
            pass
