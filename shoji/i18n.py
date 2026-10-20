# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""表示言語（日本語 / English）。

ダッシュボードの文言は shoji/assets/i18n.js にあり、ここには Python 側で作る文言
（トレイのメニュー、ブロック・警告の画面、フィルタリングログの説明、操作の結果のメッセージ）を置く。
言語は設定 app.language（"auto" / "ja" / "en"）で決まり、"auto" は Windows の表示言語に従う。
"""
from __future__ import annotations

import locale
import sys
from functools import lru_cache
from typing import Callable

LANGS = ("ja", "en")
_get_cfg: Callable[[], dict] | None = None


def configure(get_cfg: Callable[[], dict]) -> None:
    """設定を読む関数を登録する（起動時に一度）"""
    global _get_cfg
    _get_cfg = get_cfg


@lru_cache(maxsize=1)
def system_lang() -> str:
    """OS の表示言語（日本語なら "ja"、それ以外は "en"）"""
    if sys.platform == "win32":
        try:
            import ctypes
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "ja" if (langid & 0x3FF) == 0x11 else "en"
        except Exception:  # noqa: BLE001
            pass
    try:
        loc = (locale.getlocale()[0] or "").lower()
    except ValueError:
        loc = ""
    return "ja" if loc.startswith(("ja", "japanese")) else "en"


def setting() -> str:
    if _get_cfg is None:
        return "auto"
    try:
        v = (_get_cfg().get("app") or {}).get("language", "auto")
    except Exception:  # noqa: BLE001
        return "auto"
    return v if v in LANGS else "auto"


def lang() -> str:
    s = setting()
    return system_lang() if s == "auto" else s


def t(key: str, **kw) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    s = entry.get(lang()) or entry["ja"]
    return s.format(**kw) if kw else s


MESSAGES: dict[str, dict[str, str]] = {
    # ---- タスクトレイ
    "tray.open": {"ja": "ダッシュボードを開く", "en": "Open dashboard"},
    "tray.pause": {"ja": "フィルタを一時停止", "en": "Pause filtering"},
    "tray.resume": {"ja": "フィルタを再開", "en": "Resume filtering"},
    "tray.autostart": {"ja": "Windows の起動時に開始", "en": "Start with Windows"},
    "tray.log": {"ja": "ログを開く", "en": "Open log"},
    "tray.quit": {"ja": "Shoji を終了", "en": "Quit Shoji"},
    "tray.title": {"ja": "Shoji — 広告・トラッカーをブロック中", "en": "Shoji — blocking ads and trackers"},
    "tray.title.paused": {"ja": "Shoji（一時停止中）", "en": "Shoji (paused)"},
    # ---- ブロック画面
    "block.ad": {"ja": "広告", "en": "ad"},
    "block.tracker": {"ja": "トラッカー", "en": "tracker"},
    "block.title": {"ja": "{label}ページをブロックしました", "en": "Blocked an {label} page"},
    "block.title.tracker": {"ja": "{label}ページをブロックしました", "en": "Blocked a {label} page"},
    "block.lead": {"ja": "<b>{host}</b> は{label}配信先としてフィルタに登録されています。",
                   "en": "<b>{host}</b> is listed in your filters as an {label} server."},
    "block.lead.tracker": {"ja": "<b>{host}</b> は{label}配信先としてフィルタに登録されています。",
                           "en": "<b>{host}</b> is listed in your filters as a {label}."},
    "block.allow": {"ja": "このまま開く（1時間許可）", "en": "Open anyway (allow for 1 hour)"},
    "block.back": {"ja": "戻る", "en": "Go back"},
    "block.rule": {"ja": "ルール", "en": "Rule"},
    "danger.title": {"ja": "危険なサイトをブロックしました", "en": "Dangerous site blocked"},
    "danger.lead": {"ja": "<b>{host}</b> は、マルウェアの配布・フィッシング詐欺・不正な仮想通貨の採掘などに使われているサイトとして、"
                          "公開されている危険サイトのリストに登録されています。",
                    "en": "<b>{host}</b> is on public lists of sites used for spreading malware, phishing or "
                          "unauthorised cryptocurrency mining."},
    "danger.warn": {"ja": "パスワードやカード番号を入力したり、ファイルをダウンロードしたりしないでください。"
                          "心当たりのないメールや SMS のリンクから来た場合は、そのまま閉じてください。",
                    "en": "Do not enter passwords or card numbers, and do not download anything. "
                          "If you got here from an unexpected email or text message, just close this tab."},
    "danger.allow": {"ja": "危険を理解したうえで開く（1時間）", "en": "I understand the risk — open it (1 hour)"},
    # ---- フィルタリングログの説明
    "log.paused": {"ja": "一時停止中", "en": "Paused"},
    "log.allowlist": {"ja": "許可リスト・一時許可", "en": "Allowlist or temporary allow"},
    "log.docexc": {"ja": "このサイトはフィルタの例外ルール（$document）で除外", "en": "Site excluded by an exception rule ($document)"},
    "log.amp": {"ja": "AMP → 通常ページ: {url}", "en": "AMP → normal page: {url}"},
    "log.params": {"ja": "追跡パラメーター除去: {params}", "en": "Removed tracking parameters: {params}"},
    "log.cookie": {"ja": "トラッカーへの Cookie 送信を遮断", "en": "Blocked cookies sent to a tracker"},
    "log.connect": {"ja": "HTTPS を復号しないサイトのため、ドメイン単位でブロック", "en": "Blocked by domain (site is not decrypted)"},
    "log.untrusting": {"ja": "{app} は証明書を受け付けないアプリのため復号しない", "en": "{app} does not accept the certificate, so it is not decrypted"},
    "log.youtube": {"ja": "YouTube の広告データを除去（{n} 件）", "en": "Removed YouTube ad data ({n})"},
    "log.page.specific": {"ja": "サイト別の要素非表示 {n} 件", "en": "{n} site-specific hiding rules"},
    "log.page.generic": {"ja": "汎用の要素非表示 {n} 件", "en": "{n} generic hiding rules"},
    "log.page.scriptlets": {"ja": "スクリプトレット {n} 件（{names}）", "en": "{n} scriptlets ({names})"},
    "log.page.default": {"ja": "ページ用スクリプトを埋め込み", "en": "Page script injected"},
    "log.picker": {"ja": "要素の選択ブロックでルールを追加", "en": "Rule added with the element picker"},
    "log.dns": {"ja": "DNS で名前解決をブロック", "en": "Blocked at DNS"},
    "log.cname": {"ja": "CNAME で偽装したトラッカー（実体は {target}）", "en": "CNAME-cloaked tracker (really {target})"},
    "log.conn_error": {"ja": "接続エラー", "en": "Connection error"},
    "pt.paused": {"ja": "一時停止中", "en": "Paused"},
    "pt.off": {"ja": "HTTPS フィルタリングがオフ", "en": "HTTPS filtering is off"},
    "pt.nocert": {"ja": "証明書を確認できるまで HTTPS は復号しない", "en": "Not decrypting until the certificate is trusted"},
    "pt.auto": {"ja": "証明書を受け付けなかったため自動で除外", "en": "Excluded automatically after rejecting the certificate"},
    "pt.builtin": {"ja": "銀行・決済などの内蔵の除外リスト", "en": "Built-in exclusion list (banks, payments, …)"},
    "pt.user": {"ja": "HTTPS を復号しないホスト（利用者の設定）", "en": "Your list of hosts that are never decrypted"},
    "pt.allow": {"ja": "許可リスト", "en": "Allowlist"},
    # ---- ログ（shoji.log とコンソール）
    "msg.wd_proxy": {"ja": "[watchdog] Shoji が異常終了したため、プロキシ設定を元に戻しました", "en": "[watchdog] Shoji exited unexpectedly; proxy settings restored"},
    "msg.wd_dns": {"ja": "[watchdog] DNS 設定を元に戻しました", "en": "[watchdog] DNS settings restored"},
    "msg.wd_fail": {"ja": "[watchdog] 起動できませんでした: {err}", "en": "[watchdog] Could not start: {err}"},
    "msg.ff": {"ja": "[cert] Firefox（{n} プロファイル）に Windows の証明書を使う設定をしました（Firefox の再起動後に有効）",
               "en": "[cert] Configured Firefox ({n} profiles) to trust Windows certificates (takes effect after restarting Firefox)"},
    "msg.cert_ok": {"ja": "[cert] ルート証明書を確認しました。HTTPS フィルタリング有効", "en": "[cert] Root certificate verified. HTTPS filtering on"},
    "msg.cert_ask": {"ja": "[cert] ルート証明書が未インストールです。インストールの確認画面が出たら「はい」を押してください…",
                     "en": "[cert] Root certificate not installed. Click \"Yes\" when Windows asks to install it…"},
    "msg.cert_off": {"ja": "[cert] HTTPS フィルタリングは停止中です（広告ドメインのブロック・DNS フィルタは動作します）。ダッシュボードの「セットアップ」から証明書をインストールできます。",
                     "en": "[cert] HTTPS filtering is paused (domain blocking and DNS filtering still work). Install the certificate from Setup in the dashboard."},
    "msg.cert_new": {"ja": "[cert] この PC 専用のルート証明書を作成しました", "en": "[cert] Created a root certificate for this PC"},
    "msg.proxy_up": {"ja": "[proxy] HTTPS フィルタリングプロキシ起動: {addr}", "en": "[proxy] HTTPS filtering proxy started: {addr}"},
    "msg.already": {"ja": "Shoji はすでに起動しています。ダッシュボードを開きます。", "en": "Shoji is already running. Opening the dashboard."},
    "msg.dns_up": {"ja": "[dns] DNS フィルタ起動: {addrs}", "en": "[dns] DNS filter started: {addrs}"},
    "msg.dns_port": {"ja": "[dns] ポート 53 が使用中の可能性があります（インターネット接続の共有 / Hyper-V 等）。config.json の dns.listen_port を変更するか --no-dns で起動してください。",
                     "en": "[dns] Port 53 may be in use (Internet Connection Sharing, Hyper-V, …). Change dns.listen_port in config.json or start with --no-dns."},
    "msg.unclean": {"ja": "[system] 前回は設定を戻さずに終了していました（元の設定は保存済みです）", "en": "[system] Last run ended without restoring settings (the originals are saved)"},
    "msg.pac": {"ja": "自動構成スクリプト", "en": "proxy auto-config"},
    "msg.static": {"ja": "固定設定", "en": "fixed proxy"},
    "msg.proxy_set": {"ja": "[system] Windows のプロキシ設定を Shoji に向けました（{mode}。終了時に元に戻します）",
                      "en": "[system] Windows proxy now points at Shoji ({mode}; restored on exit)"},
    "msg.tray_hint": {"ja": "タスクトレイの障子アイコンから、一時停止・ダッシュボード・終了ができます。", "en": "Use the Shoji icon in the system tray to pause, open the dashboard or quit."},
    "msg.ctrl_c": {"ja": "終了するには Ctrl+C を押してください。", "en": "Press Ctrl+C to quit."},
    "msg.proxy_restored": {"ja": "[system] プロキシ設定を元に戻しました", "en": "[system] Proxy settings restored"},
    "msg.dns_restored": {"ja": "[system] DNS 設定を元に戻しました", "en": "[system] DNS settings restored"},
    "msg.stopping": {"ja": "終了処理中…", "en": "Shutting down…"},
    "msg.stopped": {"ja": "終了しました。", "en": "Stopped."},
    "msg.rules": {"ja": "[lists] ルール読込: DNS {dns} ドメイン / ネットワーク {net} / 要素非表示 {cos} ({sec}秒)",
                  "en": "[lists] Rules loaded: DNS {dns} domains / network {net} / element hiding {cos} ({sec} s)"},
    "msg.dl_fail": {"ja": "[lists] {name} のダウンロードに失敗: {err}", "en": "[lists] Could not download {name}: {err}"},
    "msg.dl_ok": {"ja": "[lists] {name} を更新 ({kb} KB)", "en": "[lists] Updated {name} ({kb} KB)"},
    "msg.update_err": {"ja": "[lists] 更新エラー: {err}", "en": "[lists] Update error: {err}"},
    "msg.app_untrust": {"ja": "[proxy] {app} は証明書を受け付けないため、このアプリの通信は HTTPS フィルタリングせずに通します{hint}",
                        "en": "[proxy] {app} does not accept the certificate, so its traffic will pass through without HTTPS filtering{hint}"},
    "msg.ff_hint": {"ja": "（Firefox は再起動すると Windows の証明書を使うようになります）", "en": " (Firefox will use Windows certificates after it restarts)"},
    "msg.host_untrust": {"ja": "[proxy] {host} は証明書を受け付けないため、以後は HTTPS 復号の対象外にします", "en": "[proxy] {host} does not accept the certificate; it will no longer be decrypted"},
    "msg.global_untrust": {"ja": "[proxy] 複数のサイトで証明書が拒否されました。ルート証明書が信頼されていないため、HTTPS フィルタリングを一時停止しました（広告ドメインのブロックは継続します）。ダッシュボードの「セットアップ」で証明書をインストールし、ブラウザを再起動してください。",
                           "en": "[proxy] Several sites rejected the certificate, so the root certificate is not trusted. HTTPS filtering is paused (domain blocking continues). Install the certificate from Setup in the dashboard and restart your browser."},
    "msg.no_tray": {"ja": "[tray] pystray が見つからないため、タスクトレイには表示しません（pip install pystray pillow）", "en": "[tray] pystray not found; no tray icon (pip install pystray pillow)"},
    # ---- 「このサイトでは止める」確認画面
    "site.title": {"ja": "{host} で Shoji を止めますか？", "en": "Turn Shoji off on {host}?"},
    "site.desc": {"ja": "このサイトでは、広告・トラッカーのブロック、要素の非表示、ステルスモードなどのフィルタをすべて止めます。"
                        "表示が崩れるときや、広告を表示してサイトを応援したいときに使います。",
                  "en": "Ad and tracker blocking, element hiding, stealth mode and the other filters will be off on this site. "
                        "Use this when a site breaks, or to support a site by seeing its ads."},
    "site.note": {"ja": "危険なサイト（マルウェア・フィッシング）へのブロックは、このサイトの中でも続きます。"
                        "「常に」を選んだ場合は、ダッシュボードの「許可リスト」からいつでも元に戻せます。",
                  "en": "Dangerous sites (malware, phishing) are still blocked inside this site. "
                        "If you choose \"always\", you can undo it any time under Allowlist in the dashboard."},
    "site.temp": {"ja": "1 時間だけ止める", "en": "Turn off for 1 hour"},
    "site.always": {"ja": "このサイトでは常に止める", "en": "Always off on this site"},
    "site.cancel": {"ja": "キャンセル", "en": "Cancel"},
    "log.site_allowed_temp": {"ja": "このサイトでフィルタを 1 時間止めた", "en": "Filtering turned off on this site for 1 hour"},
    "log.site_allowed_always": {"ja": "このサイトを許可リストに追加", "en": "Site added to the allowlist"},
    # ---- 要素の選択ブロックの保存
    "picker.bad": {"ja": "不正なデータ", "en": "Invalid data"},
    "picker.format": {"ja": "ルールの形式が正しくありません", "en": "The rule is not in the right format"},
    "picker.site": {"ja": "このサイト以外のルールは追加できません", "en": "Rules can only be added for this site"},
    "picker.selector": {"ja": "このセレクタは使えません", "en": "This selector is not allowed"},
    "picker.rate": {"ja": "短時間に追加しすぎです", "en": "Too many rules in a short time"},
    "picker.comment": {"ja": "要素の選択ブロックで追加 ({time})", "en": "Added with the element picker ({time})"},
    "sc.invalid": {"ja": "このショートカットは使えません（Ctrl か Alt を含む組み合わせ、または F1〜F12 にしてください）",
                   "en": "This shortcut cannot be used (use a combination with Ctrl or Alt, or F1–F12)"},
    "rule.invalid": {"ja": "ルールが正しくありません", "en": "Invalid rule"},
    # ---- Windows の設定
    "win.only": {"ja": "Windows 専用の機能です", "en": "This works on Windows only"},
    "win.admin_set": {"ja": "管理者権限が必要です（set_dns.bat を「管理者として実行」してください）",
                      "en": "Administrator rights are needed (right-click set_dns.bat → Run as administrator)"},
    "win.admin_reset": {"ja": "管理者権限が必要です（reset_dns.bat を「管理者として実行」してください）",
                        "en": "Administrator rights are needed (right-click reset_dns.bat → Run as administrator)"},
    "win.dns_set": {"ja": "DNS を 127.0.0.1 に設定しました", "en": "DNS set to 127.0.0.1"},
    "win.dns_reset": {"ja": "DNS を自動取得（DHCP）に戻しました", "en": "DNS restored to automatic (DHCP)"},
    "win.dns_failed": {"ja": "DNS の設定に失敗しました: {err}", "en": "Could not change DNS: {err}"},
    "cert.missing": {"ja": "証明書がまだ生成されていません（一度起動してください）", "en": "The certificate has not been generated yet (start Shoji once)"},
    "cert.installed": {"ja": "証明書をインストールしました。ブラウザ（Edge）をいったん全部閉じてから開き直してください",
                       "en": "Certificate installed. Close all browser windows and open the browser again"},
    "cert.cancelled": {"ja": "証明書の登録がキャンセルされたか、確認できませんでした。もう一度お試しください",
                       "en": "The certificate was not installed (cancelled or could not be confirmed). Please try again"},
    "https.checking": {"ja": "証明書の確認中", "en": "Checking the certificate"},
    "https.nocert": {"ja": "証明書が未インストールのため HTTPS フィルタリング停止中", "en": "HTTPS filtering paused: certificate not installed"},
    "https.untrusted": {"ja": "ブラウザが証明書を信頼していません（証明書を再インストールしてください）",
                        "en": "The browser does not trust the certificate (reinstall the certificate)"},
}
