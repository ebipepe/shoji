# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""統計レポート・設定画面（http://127.0.0.1:8765）。"""
from __future__ import annotations

import csv
import io
import threading
import time

from flask import Flask, Response, jsonify, request, send_file
from werkzeug.serving import WSGIRequestHandler, make_server

from . import __version__, i18n, lists, stats as stats_mod, winsys
from .config import ASSETS_DIR, BUILTIN_HTTPS_EXCLUSIONS, DEFAULT_SHORTCUTS, STATS_DB, normalize_shortcut
from .context import AppContext


def pac_url(ctx: AppContext) -> str:
    d = ctx.cfg["dashboard"]
    return f"http://127.0.0.1:{d['listen_port']}/proxy.pac"


def apply_system_proxy(ctx: AppContext) -> bool:
    """設定（PAC / 固定）に従って Windows のプロキシ設定を Shoji に向ける"""
    p = ctx.cfg["proxy"]
    return winsys.set_system_proxy(p["listen_host"], p["listen_port"],
                                   p.get("system_proxy_mode", "pac"), pac_url(ctx))


def create_app(ctx: AppContext) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.after_request
    def _no_cache(resp):
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.before_request
    def _csrf():
        # 他サイトからの勝手な設定変更を防ぐ（同一オリジンのみ許可）
        if request.method == "POST":
            origin = request.headers.get("Origin", "")
            if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
                return jsonify({"ok": False, "error": "forbidden"}), 403

    @app.get("/")
    def index():
        return send_file(ASSETS_DIR / "dashboard.html")

    @app.get("/proxy.pac")
    def proxy_pac():
        # Windows / ブラウザが読む自動構成スクリプト。Shoji が止まると取得できなくなり、直接接続に戻る
        p = ctx.cfg["proxy"]
        host = "127.0.0.1" if p["listen_host"] in ("0.0.0.0", "::") else p["listen_host"]
        return Response(winsys.pac_script(host, int(p["listen_port"])),
                        mimetype="application/x-ns-proxy-autoconfig")

    @app.post("/api/pause")
    def pause():
        on = bool((request.get_json(force=True) or {}).get("paused"))
        ctx.set_paused(on)
        return jsonify({"ok": True, "paused": ctx.paused})

    @app.post("/api/autostart")
    def autostart():
        on = bool((request.get_json(force=True) or {}).get("on"))
        ok = winsys.set_autostart(on)
        return jsonify({"ok": ok, "autostart": winsys.get_autostart()})

    @app.get("/i18n.js")
    def i18n_js():
        return send_file(ASSETS_DIR / "i18n.js", mimetype="text/javascript")

    @app.get("/icon.svg")
    def icon():
        return send_file(ASSETS_DIR / "icon.svg", mimetype="image/svg+xml")

    @app.get("/api/status")
    def status():
        cfg = ctx.cfg
        p = cfg["proxy"]
        return jsonify({
            "version": __version__,
            "uptime": int(time.time() - ctx.started_at),
            "status": ctx.status,
            "live": ctx.stats.live(),
            "is_windows": winsys.IS_WIN,
            "is_admin": winsys.is_admin(),
            "system_proxy": winsys.system_proxy_points_to(p["listen_host"], p["listen_port"], pac_url(ctx)),
            "proxy_mode": p.get("system_proxy_mode", "pac"),
            "paused": ctx.paused,
            "autostart": winsys.get_autostart(),
            "cert_installed": winsys.ca_cert_installed(),
            "https_ready": ctx.https_ready,
            "https_problem": i18n.t(ctx.https_problem) if ctx.https_problem in i18n.MESSAGES else ctx.https_problem,
            "lang": i18n.lang(),
            "lang_setting": i18n.setting(),
            "cert_path": str(winsys.ca_cert_path()),
            "passthrough_hosts": sorted(ctx.passthrough_hosts),
            "untrusting_apps": sorted(ctx.untrusting_apps),
            "builtin_exclusions": list(BUILTIN_HTTPS_EXCLUSIONS),
            "proxy_addr": f"{p['listen_host']}:{p['listen_port']}",
            "dns_addr": f"{cfg['dns']['listen_host']}:{cfg['dns']['listen_port']}",
        })

    @app.get("/api/log")
    def get_log():
        a = request.args
        items = ctx.reqlog.query(since=int(a.get("since", "0") or 0), limit=int(a.get("limit", "500") or 500),
                                 action=a.get("action", ""), q=a.get("q", ""), page=a.get("page", ""))
        return jsonify({"items": items, "last": ctx.reqlog.last_id(), "enabled": ctx.reqlog.enabled})

    @app.post("/api/log/clear")
    def clear_log():
        ctx.reqlog.clear()
        return jsonify({"ok": True})

    @app.post("/api/log/enabled")
    def log_enabled():
        ctx.reqlog.enabled = bool((request.get_json(force=True) or {}).get("on"))
        return jsonify({"ok": True, "enabled": ctx.reqlog.enabled})

    @app.post("/api/user_rules/add")
    def add_user_rule():
        """フィルタリングログから 1 行のルールを追加する"""
        rule = str((request.get_json(force=True) or {}).get("rule", "")).strip()
        if not rule or "\n" in rule or "\r" in rule or len(rule) > 2000:
            return jsonify({"ok": False, "error": i18n.t("rule.invalid")}), 400
        if not lists.add_user_rule(rule):
            return jsonify({"ok": True, "added": False})
        threading.Thread(target=lists.load_engine, args=(ctx,), daemon=True).start()
        return jsonify({"ok": True, "added": True})

    @app.get("/api/report")
    def report():
        days = int(request.args.get("days", "1") or 0)
        ctx.stats.flush()
        return jsonify(stats_mod.report(days or None, STATS_DB))

    @app.get("/api/report.csv")
    def report_csv():
        days = int(request.args.get("days", "30") or 0)
        ctx.stats.flush()
        rep = stats_mod.report(days or None, STATS_DB)
        cats = ["ad", "tracker", "popup", "youtube", "reinserted", "cosmetic", "amp",
                "stealth_param", "stealth_cookie", "stealth_header", "request", "dns_query"]
        buf = io.StringIO()
        w = csv.writer(buf)
        if i18n.lang() == "ja":
            w.writerow(["日付", "広告", "トラッカー", "ポップアップ", "動画広告", "再挿入広告", "要素非表示", "AMP",
                        "追跡パラメーター", "Cookie遮断", "追跡ヘッダー", "HTTPリクエスト", "DNS問い合わせ"])
        else:
            w.writerow(["Date", "Ads", "Trackers", "Pop-ups", "Video ads", "Re-inserted ads", "Hidden elements", "AMP",
                        "Tracking parameters", "Cookies blocked", "Tracking headers", "HTTP requests", "DNS queries"])
        for day in sorted(rep["daily"]):
            w.writerow([day] + [rep["daily"][day].get(c, 0) for c in cats])
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=shoji_report.csv"})

    @app.post("/api/stats/reset")
    def reset_stats():
        ctx.stats.flush()
        stats_mod.reset(STATS_DB)
        return jsonify({"ok": True})

    @app.get("/api/config")
    def get_config():
        return jsonify(ctx.cfg)

    @app.post("/api/config")
    def set_config():
        patch = request.get_json(force=True) or {}
        allowed = {"features", "stealth", "whitelist", "https_exclusions", "filter_lists",
                   "update_interval_hours", "dns", "proxy", "app"}
        patch = {k: v for k, v in patch.items() if k in allowed}
        sc = patch["app"].get("shortcuts") if isinstance(patch.get("app"), dict) else None
        if sc is not None:
            if not isinstance(sc, dict):
                return jsonify({"ok": False, "error": "bad shortcuts"}), 400
            clean = {}
            for name, value in sc.items():
                if name not in DEFAULT_SHORTCUTS:
                    continue
                v = normalize_shortcut(value)
                if v is None:
                    return jsonify({"ok": False, "error": i18n.t("sc.invalid")}), 400
                clean[name] = v
            patch["app"]["shortcuts"] = clean
        reload_lists = "filter_lists" in patch
        ctx.config.update(patch)
        if "app" in patch:
            for cb in list(ctx.on_ui_change):
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    pass
        if reload_lists:
            def _reload():
                # 新しく有効にしたリストがまだ無ければダウンロードしてから読み込む
                if not lists.update_lists(ctx):
                    lists.load_engine(ctx)
            threading.Thread(target=_reload, daemon=True).start()
        return jsonify({"ok": True, "config": ctx.cfg})

    @app.get("/api/user_rules")
    def get_rules():
        p = lists.USER_RULES
        return jsonify({"text": p.read_text(encoding="utf-8") if p.exists() else ""})

    @app.post("/api/user_rules")
    def set_rules():
        text = (request.get_json(force=True) or {}).get("text", "")
        lists.USER_RULES.write_text(text, encoding="utf-8")
        threading.Thread(target=lists.load_engine, args=(ctx,), daemon=True).start()
        return jsonify({"ok": True})

    @app.get("/api/lists")
    def get_lists():
        return jsonify({"lists": lists.list_status(ctx), "summary": ctx.status.get("lists")})

    @app.post("/api/lists/update")
    def update_lists():
        def run():
            ctx.status["updating"] = True
            try:
                lists.update_lists(ctx, force=True)
            finally:
                ctx.status["updating"] = False
        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True})

    @app.get("/api/check")
    def check_url():
        """URL がブロックされるかを調べる（ルールのテスト用）"""
        from urllib.parse import urlsplit
        url = request.args.get("url", "")
        page = request.args.get("page", "")
        host = (urlsplit(url).hostname or "").lower()
        page_host = (urlsplit(page).hostname or host).lower() if page else host
        rtype = request.args.get("type", "other")
        rule = ctx.engine.match_url(url, host, page_host, rtype)
        return jsonify({"url": url, "blocked": bool(rule), "rule": rule.raw if rule else None,
                        "category": ctx.engine.categorize(host, rule.category) if rule else None,
                        "dns": ctx.engine.dns_lookup(host)})

    @app.post("/api/system/proxy")
    def sys_proxy():
        on = bool((request.get_json(force=True) or {}).get("on"))
        ok = apply_system_proxy(ctx) if on else winsys.restore_system_proxy()
        return jsonify({"ok": ok})

    @app.post("/api/system/dns")
    def sys_dns():
        on = bool((request.get_json(force=True) or {}).get("on"))
        ok, msg = winsys.set_system_dns() if on else winsys.reset_system_dns()
        return jsonify({"ok": ok, "message": msg})

    @app.post("/api/system/cert")
    def sys_cert():
        ok, msg = winsys.install_ca_cert()
        if ok:
            ctx.cert_verified = True
            ctx.set_https_ready(True)
            ctx.passthrough_hosts.clear()
            ctx._save_passthrough()
        return jsonify({"ok": ok, "message": msg})

    @app.post("/api/passthrough/clear")
    def clear_passthrough():
        ctx.passthrough_hosts.clear()
        ctx._save_passthrough()
        ctx.clear_untrusting_apps()
        return jsonify({"ok": True})

    @app.get("/cert")
    def cert():
        p = winsys.ca_cert_path()
        if not p.exists():
            return "not generated", 404
        return send_file(p, as_attachment=True, download_name="shoji-ca.cer")

    return app


class _QuietHandler(WSGIRequestHandler):
    """ダッシュボードは 5 秒ごとに状態を取得するため、成功したアクセスはログに残さない"""

    def log_request(self, code="-", size="-"):
        if str(code).startswith(("4", "5")):
            super().log_request(code, size)


class DashboardServer:
    def __init__(self, ctx: AppContext):
        d = ctx.cfg["dashboard"]
        self.server = make_server(d["listen_host"], int(d["listen_port"]), create_app(ctx), threaded=True,
                                  request_handler=_QuietHandler)
        self.url = f"http://{d['listen_host']}:{d['listen_port']}/"
        self.thread = threading.Thread(target=self.server.serve_forever, name="dashboard", daemon=True)

    def start(self):
        self.thread.start()
        return self.url

    def stop(self):
        self.server.shutdown()
