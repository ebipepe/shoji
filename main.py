# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""Shoji 起動スクリプト。

  python main.py                 すべて起動（HTTPS フィルタ + DNS + ダッシュボード + タスクトレイ）
  python main.py --no-dns        DNS フィルタを起動しない
  python main.py --no-system-proxy  Windows のプロキシ設定を変更しない
  python main.py --update-lists  フィルタリストを強制更新してから起動
  python main.py --no-tray       タスクトレイに表示しない（コンソールで Ctrl+C で終了）
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

from shoji import __version__, depcheck, i18n, lists, winsys
from shoji.config import CERT_DIR, DATA_DIR, LOG_PATH, Config
from shoji.context import AppContext
from shoji.filters import FilterEngine
from shoji.stats import Stats


# ---------------------------------------------------------------- ログ
class _Tee(io.TextIOBase):
    """コンソール（あれば）とログファイルの両方に書き出す"""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except (OSError, ValueError):
                pass
        return len(s)

    def flush(self):
        pass


def setup_logging() -> None:
    """ログを data/shoji.log にも残す（コンソールの無い exe / pythonw 起動でも原因を追えるように）"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2_000_000:
            LOG_PATH.replace(LOG_PATH.with_suffix(".old.log"))
        log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — プロセス終了まで開いておく
    except OSError:
        log = None
    con_out, con_err = sys.stdout, sys.stderr
    for con in (con_out, con_err):
        try:
            con.reconfigure(encoding="utf-8")   # コンソールの文字化け防止
        except (AttributeError, ValueError):
            pass
    sys.stdout = _Tee(con_out, log)
    sys.stderr = _Tee(con_err, log)
    print(f"\n----- {time.strftime('%Y-%m-%d %H:%M:%S')} -----")


# ---------------------------------------------------------------- 異常終了対策
def run_watchdog(pid: int) -> None:
    """本体（pid）が終了するまで待ち、設定を戻さずに落ちていたら元に戻す。
    クラッシュや強制終了でネットにつながらなくなるのを防ぐ。"""
    winsys.wait_for_process_exit(pid)
    time.sleep(1.5)
    if winsys.system_proxy_needs_restore():
        winsys.restore_system_proxy()
        print(i18n.t("msg.wd_proxy"))
    if winsys.dns_was_set_by_us() and winsys.is_admin():
        winsys.reset_system_dns()
        print(i18n.t("msg.wd_dns"))


def start_watchdog() -> None:
    if not winsys.IS_WIN:
        return
    flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    try:
        subprocess.Popen(winsys.launch_command("--watchdog", str(os.getpid())), creationflags=flags,
                         close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError as e:
        print(i18n.t("msg.wd_fail", err=e))


# ---------------------------------------------------------------- 各部品
def config_watcher(ctx: AppContext, stop: threading.Event):
    """設定ファイルの変更（手動編集を含む）を検知して反映する"""
    while not stop.wait(2):
        ctx.config.reload()


def ensure_cert(ctx: AppContext):
    """ルート証明書がインストール済みか確認し、無ければインストールを試みる。
    確認できるまでは HTTPS を復号しない（復号すると全サイトが証明書エラーになるため）。"""
    for _ in range(50):                       # mitmproxy が証明書を生成するのを待つ
        if winsys.ca_cert_path().exists():
            break
        time.sleep(0.2)
    if not winsys.IS_WIN:
        ctx.set_https_ready(True)
        return
    n = winsys.enable_firefox_windows_roots()
    if n:
        print(i18n.t("msg.ff", n=n))
    if winsys.ca_cert_installed_fresh():
        ctx.cert_verified = True
        ctx.set_https_ready(True)
        print(i18n.t("msg.cert_ok"))
        return
    print(i18n.t("msg.cert_ask"))
    ok, msg = winsys.install_ca_cert()
    if ok:
        ctx.cert_verified = True
        ctx.set_https_ready(True)
        print("[cert] " + msg)
    else:
        ctx.set_https_ready(False, "https.nocert")
        print("[cert] " + msg)
        print(i18n.t("msg.cert_off"))


async def run_proxy(ctx: AppContext, stop_event: asyncio.Event):
    from mitmproxy import options
    from mitmproxy.tools.dump import DumpMaster

    from shoji.proxy_addon import ShojiAddon

    p = ctx.cfg["proxy"]
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    if not (CERT_DIR / "mitmproxy-ca.pem").exists():
        # この PC 専用のルート証明書を作る（Windows の確認画面で分かりやすい名前にする）
        from mitmproxy import certs
        certs.CertStore.create_store(CERT_DIR, "mitmproxy", 2048, organization="Shoji",
                                     cn="Shoji Local Filtering CA (this PC only)")
        print(i18n.t("msg.cert_new"))
    opts = options.Options(listen_host=p["listen_host"], listen_port=int(p["listen_port"]),
                           confdir=str(CERT_DIR))
    master = DumpMaster(opts, with_termlog=False, with_dumper=False)
    master.options.update(
        connection_strategy="lazy",     # ブロックする通信は上流に接続すらしない
        stream_large_bodies="3m",       # 大きなファイル（動画等）はそのまま流す
        http2=True,
        ssl_insecure=False,
        block_global=False,
    )
    master.addons.add(ShojiAddon(ctx))
    loop = asyncio.get_running_loop()
    ctx.request_exit = lambda: loop.call_soon_threadsafe(stop_event.set)
    threading.Thread(target=ensure_cert, args=(ctx,), daemon=True).start()
    task = asyncio.create_task(master.run())
    ctx.status["proxy"] = "running"
    print(i18n.t("msg.proxy_up", addr=f"{p['listen_host']}:{p['listen_port']}"))
    await stop_event.wait()
    master.shutdown()
    try:
        await asyncio.wait_for(task, 5)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        pass
    ctx.status["proxy"] = "stopped"


# ---------------------------------------------------------------- 起動
def main():
    ap = argparse.ArgumentParser(description="Shoji - 広告/トラッカーブロッカー")
    ap.add_argument("--no-dns", action="store_true", help="DNS フィルタを起動しない")
    ap.add_argument("--no-proxy", action="store_true", help="HTTPS フィルタリングプロキシを起動しない")
    ap.add_argument("--no-system-proxy", action="store_true", help="Windows のプロキシ設定を変更しない")
    ap.add_argument("--no-browser", action="store_true", help="ダッシュボードを自動で開かない")
    ap.add_argument("--update-lists", action="store_true", help="フィルタリストを強制更新する")
    ap.add_argument("--no-tray", action="store_true", help="タスクトレイに表示しない")
    ap.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)   # Windows 起動時の自動起動
    ap.add_argument("--watchdog", type=int, metavar="PID", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=f"Shoji {__version__}")
    args = ap.parse_args()

    setup_logging()
    if args.watchdog:
        run_watchdog(args.watchdog)
        return

    print(f"=== Shoji v{__version__} ===")
    if not winsys.acquire_single_instance():
        # すでに起動している場合はダッシュボードを開くだけ
        print(i18n.t("msg.already"))
        if not args.autostart:
            port = Config().get()["dashboard"]["listen_port"]
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return

    config = Config()
    i18n.configure(config.get)
    stats = Stats()
    ctx = AppContext(config, stats, FilterEngine())
    ctx.deps_outdated = depcheck.check()
    if ctx.deps_outdated:
        print(i18n.t("msg.deps_outdated", items=depcheck.describe(ctx.deps_outdated)))

    # まず内蔵ルール＋手元のリストで即座に起動し、ダウンロードは裏で行う
    lists.load_engine(ctx)
    if args.update_lists:
        threading.Thread(target=lists.update_lists, args=(ctx, True), daemon=True).start()
    lists.start_updater(ctx)

    stop_thread = threading.Event()
    threading.Thread(target=config_watcher, args=(ctx, stop_thread), daemon=True).start()

    dns = None
    if not args.no_dns:
        from shoji.dns_server import DnsFilter
        try:
            dns = DnsFilter(ctx)
            addrs = dns.start()
            ctx.status["dns"] = "running"
            print(i18n.t("msg.dns_up", addrs=", ".join(addrs)))
        except OSError as e:
            ctx.status["dns"] = "error"
            print(f"[dns] {e}")
            print(i18n.t("msg.dns_port"))

    from shoji.dashboard import DashboardServer, apply_system_proxy
    dash = DashboardServer(ctx)
    url = dash.start()
    print(f"[dashboard] {url}")

    proxy_set = False
    p = ctx.cfg["proxy"]
    if not args.no_proxy and not args.no_system_proxy and p.get("set_system_proxy", True):
        if winsys.system_proxy_needs_restore():
            print(i18n.t("msg.unclean"))
        start_watchdog()
        proxy_set = apply_system_proxy(ctx)
        if proxy_set:
            mode = i18n.t("msg.pac") if p.get("system_proxy_mode", "pac") == "pac" else i18n.t("msg.static")
            print(i18n.t("msg.proxy_set", mode=mode))

    exit_event = threading.Event()
    tray = None
    if not args.no_tray and winsys.IS_WIN and ctx.cfg.get("app", {}).get("tray", True):
        from shoji.tray import Tray

        def _exit_from_tray():
            exit_event.set()
            if ctx.request_exit:
                ctx.request_exit()
        tray = Tray(ctx, url, _exit_from_tray)
        if not tray.start():
            tray = None

    if not args.no_browser and not args.autostart and ctx.cfg.get("app", {}).get("open_dashboard_on_start", True):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    if tray:
        print(i18n.t("msg.tray_hint"))
    else:
        print(i18n.t("msg.ctrl_c"))

    def cleanup():
        stop_thread.set()
        if tray:
            tray.stop()
        if proxy_set:
            winsys.restore_system_proxy()
            print(i18n.t("msg.proxy_restored"))
        if winsys.dns_was_set_by_us() and winsys.is_admin():
            winsys.reset_system_dns()
            print(i18n.t("msg.dns_restored"))
        if dns:
            dns.stop()
        stats.close()

    failed = False
    try:
        if args.no_proxy:
            ctx.request_exit = exit_event.set
            exit_event.wait()
        else:
            async def runner():
                stop_event = asyncio.Event()
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(sig, stop_event.set)
                    except (NotImplementedError, RuntimeError):
                        pass   # Windows では KeyboardInterrupt で抜ける
                await run_proxy(ctx, stop_event)
            asyncio.run(runner())
    except KeyboardInterrupt:
        pass
    except Exception:   # noqa: BLE001 — exe ではエラー画面ではなくログに残す
        traceback.print_exc()
        failed = True
    finally:
        print(i18n.t("msg.stopping"))
        cleanup()
        print(i18n.t("msg.stopped"))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
