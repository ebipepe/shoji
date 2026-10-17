# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""Shoji 起動スクリプト。

  python main.py                 すべて起動（HTTPS フィルタ + DNS + ダッシュボード）
  python main.py --no-dns        DNS フィルタを起動しない
  python main.py --no-system-proxy  Windows のプロキシ設定を変更しない
  python main.py --update-lists  フィルタリストを強制更新してから起動
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading
import webbrowser

if sys.platform == "win32":
    # コンソールの文字化け防止
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from shoji import __version__, lists, winsys
from shoji.config import CERT_DIR, Config
from shoji.context import AppContext
from shoji.filters import FilterEngine
from shoji.stats import Stats


def config_watcher(ctx: AppContext, stop: threading.Event):
    """設定ファイルの変更（手動編集を含む）を検知して反映する"""
    while not stop.wait(2):
        ctx.config.reload()


def ensure_cert(ctx: AppContext):
    """ルート証明書がインストール済みか確認し、無ければインストールを試みる。
    確認できるまでは HTTPS を復号しない（復号すると全サイトが証明書エラーになるため）。"""
    import time
    for _ in range(50):                       # mitmproxy が証明書を生成するのを待つ
        if winsys.ca_cert_path().exists():
            break
        time.sleep(0.2)
    if not winsys.IS_WIN:
        ctx.set_https_ready(True)
        return
    n = winsys.enable_firefox_windows_roots()
    if n:
        print(f"[cert] Firefox（{n} プロファイル）に Windows の証明書を使う設定をしました（Firefox の再起動後に有効）")
    if winsys.ca_cert_installed_fresh():
        ctx.cert_verified = True
        ctx.set_https_ready(True)
        print("[cert] ルート証明書を確認しました。HTTPS フィルタリング有効")
        return
    print("[cert] ルート証明書が未インストールです。インストールの確認画面が出たら「はい」を押してください…")
    ok, msg = winsys.install_ca_cert()
    if ok:
        ctx.cert_verified = True
        ctx.set_https_ready(True)
        print("[cert] " + msg)
    else:
        ctx.set_https_ready(False, "証明書が未インストールのため HTTPS フィルタリング停止中")
        print("[cert] " + msg)
        print("[cert] HTTPS フィルタリングは停止中です（広告ドメインのブロック・DNS フィルタは動作します）。"
              "ダッシュボードの「セットアップ」から証明書をインストールできます。")


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
        print("[cert] この PC 専用のルート証明書を作成しました")
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
    threading.Thread(target=ensure_cert, args=(ctx,), daemon=True).start()
    task = asyncio.create_task(master.run())
    ctx.status["proxy"] = "running"
    print(f"[proxy] HTTPS フィルタリングプロキシ起動: {p['listen_host']}:{p['listen_port']}")
    await stop_event.wait()
    master.shutdown()
    try:
        await asyncio.wait_for(task, 5)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        pass
    ctx.status["proxy"] = "stopped"


def main():
    ap = argparse.ArgumentParser(description="Shoji - 広告/トラッカーブロッカー")
    ap.add_argument("--no-dns", action="store_true", help="DNS フィルタを起動しない")
    ap.add_argument("--no-proxy", action="store_true", help="HTTPS フィルタリングプロキシを起動しない")
    ap.add_argument("--no-system-proxy", action="store_true", help="Windows のプロキシ設定を変更しない")
    ap.add_argument("--no-browser", action="store_true", help="ダッシュボードを自動で開かない")
    ap.add_argument("--update-lists", action="store_true", help="フィルタリストを強制更新する")
    args = ap.parse_args()

    print(f"=== Shoji v{__version__} ===")
    config = Config()
    stats = Stats()
    ctx = AppContext(config, stats, FilterEngine())

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
            print("[dns] DNS フィルタ起動: " + ", ".join(addrs))
        except OSError as e:
            ctx.status["dns"] = "error"
            print(f"[dns] {e}")
            print("[dns] ポート 53 が使用中の可能性があります（インターネット接続の共有 / Hyper-V 等）。"
                  "config.json の dns.listen_port を変更するか --no-dns で起動してください。")

    from shoji.dashboard import DashboardServer
    dash = DashboardServer(ctx)
    url = dash.start()
    print(f"[dashboard] {url}")

    proxy_set = False
    p = ctx.cfg["proxy"]
    if not args.no_proxy and not args.no_system_proxy and p.get("set_system_proxy", True):
        proxy_set = winsys.set_system_proxy(p["listen_host"], p["listen_port"])
        if proxy_set:
            print("[system] Windows のプロキシ設定を Shoji に向けました（終了時に元に戻します）")

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    print("終了するには Ctrl+C を押してください。")

    def cleanup():
        stop_thread.set()
        if proxy_set:
            winsys.restore_system_proxy()
            print("[system] プロキシ設定を元に戻しました")
        if winsys.dns_was_set_by_us() and winsys.is_admin():
            winsys.reset_system_dns()
            print("[system] DNS 設定を元に戻しました")
        if dns:
            dns.stop()
        stats.close()

    try:
        if args.no_proxy:
            threading.Event().wait()
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
    finally:
        print("\n終了処理中…")
        cleanup()
        print("終了しました。")


if __name__ == "__main__":
    main()
