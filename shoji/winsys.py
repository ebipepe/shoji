# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""Windows のシステム設定（プロキシ・DNS・証明書）を操作する。Windows 以外では何もしない。"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys

from .config import CERT_DIR, DATA_DIR

IS_WIN = sys.platform == "win32"
SAVED = DATA_DIR / "saved_network.json"
_INET_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
_BYPASS = "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.2*;172.30.*;172.31.*;192.168.*;<local>"


def is_admin() -> bool:
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _load_saved() -> dict:
    try:
        return json.loads(SAVED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    SAVED.parent.mkdir(parents=True, exist_ok=True)
    SAVED.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _refresh_wininet() -> None:
    # INTERNET_OPTION_SETTINGS_CHANGED=39, INTERNET_OPTION_REFRESH=37
    try:
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(0, 39, 0, 0)
        wininet.InternetSetOptionW(0, 37, 0, 0)
    except OSError:
        pass


# ------------------------------------------------------------------ プロキシ
def get_system_proxy() -> dict:
    if not IS_WIN:
        return {"enabled": False, "server": "", "bypass": "", "pac": ""}
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_KEY) as k:
        def q(name, default):
            try:
                return winreg.QueryValueEx(k, name)[0]
            except OSError:
                return default
        return {"enabled": bool(q("ProxyEnable", 0)), "server": q("ProxyServer", ""),
                "bypass": q("ProxyOverride", ""), "pac": q("AutoConfigURL", "")}


def pac_script(host: str, port: int) -> str:
    """自動構成スクリプト（PAC）。Shoji が止まっていればブラウザは自動で直接接続に戻る。"""
    return f"""function FindProxyForURL(url, host) {{
  if (isPlainHostName(host) || host === "localhost" || shExpMatch(host, "*.localhost") ||
      shExpMatch(host, "127.*") || shExpMatch(host, "10.*") || shExpMatch(host, "192.168.*") ||
      /^172\\.(1[6-9]|2[0-9]|3[01])\\./.test(host) ||
      shExpMatch(host, "169.254.*") || host === "[::1]") {{
    return "DIRECT";
  }}
  return "PROXY {host}:{port}; DIRECT";
}}
"""


def set_system_proxy(host: str, port: int, mode: str = "static", pac_url: str = "") -> bool:
    """Windows のプロキシ設定を Shoji に向ける。変更前の設定は保存し、restore で戻す。
    mode="pac": 自動構成スクリプトを使う（推奨。Shoji が落ちてもネットが切れない）
    mode="static": 固定のプロキシ設定"""
    if not IS_WIN:
        return False
    import winreg
    saved = _load_saved()
    cur = get_system_proxy()
    target = f"{host}:{port}"
    if "proxy" not in saved and cur.get("server") != target and cur.get("pac") != pac_url:
        saved["proxy"] = cur
        _save(saved)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if mode == "pac" and pac_url:
            winreg.SetValueEx(k, "AutoConfigURL", 0, winreg.REG_SZ, pac_url)
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        else:
            _delete_value(k, "AutoConfigURL")
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, target)
            winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, _BYPASS)
    _refresh_wininet()
    return True


def _delete_value(key, name: str) -> None:
    import winreg
    try:
        winreg.DeleteValue(key, name)
    except OSError:
        pass


def restore_system_proxy() -> bool:
    if not IS_WIN:
        return False
    import winreg
    saved = _load_saved()
    prev = saved.pop("proxy", {"enabled": False, "server": "", "bypass": "", "pac": ""})
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1 if prev.get("enabled") else 0)
        winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, prev.get("server", ""))
        winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, prev.get("bypass", ""))
        if prev.get("pac"):
            winreg.SetValueEx(k, "AutoConfigURL", 0, winreg.REG_SZ, prev["pac"])
        else:
            _delete_value(k, "AutoConfigURL")
    _save(saved)
    _refresh_wininet()
    return True


def system_proxy_needs_restore() -> bool:
    """前回 Shoji が設定を戻さずに終了した（異常終了・強制終了）か"""
    return "proxy" in _load_saved()


def system_proxy_points_to(host: str, port: int, pac_url: str = "") -> bool:
    p = get_system_proxy()
    return (p["enabled"] and p["server"] == f"{host}:{port}") or (bool(pac_url) and p.get("pac") == pac_url)


# ------------------------------------------------------------------ DNS
def _ps(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                          capture_output=True, text=True, timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def set_system_dns() -> tuple[bool, str]:
    """有効なネットワークアダプターの DNS を 127.0.0.1 / ::1 にする（管理者権限が必要）"""
    if not IS_WIN:
        return False, "Windows 専用の機能です"
    if not is_admin():
        return False, "管理者権限が必要です（set_dns.bat を「管理者として実行」してください）"
    r = _ps("Get-NetAdapter | Where-Object Status -eq 'Up' | ForEach-Object { "
            "Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses ('127.0.0.1','::1') }; "
            "Clear-DnsClientCache")
    if r.returncode == 0:
        s = _load_saved()
        s["dns"] = True
        _save(s)
        return True, "DNS を 127.0.0.1 に設定しました"
    return False, r.stderr.strip()[:500]


def reset_system_dns() -> tuple[bool, str]:
    if not IS_WIN:
        return False, "Windows 専用の機能です"
    if not is_admin():
        return False, "管理者権限が必要です（reset_dns.bat を「管理者として実行」してください）"
    r = _ps("Get-NetAdapter | ForEach-Object { Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex "
            "-ResetServerAddresses }; Clear-DnsClientCache")
    s = _load_saved()
    s.pop("dns", None)
    _save(s)
    return r.returncode == 0, (r.stderr.strip()[:500] or "DNS を自動取得に戻しました")


def system_dns_is_local() -> bool:
    if not IS_WIN:
        return False
    r = _ps("(Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object ServerAddresses -contains "
            "'127.0.0.1' | Measure-Object).Count")
    return r.stdout.strip() not in ("", "0")


def dns_was_set_by_us() -> bool:
    return bool(_load_saved().get("dns"))


# ------------------------------------------------------------------ 証明書
def ca_cert_path():
    return CERT_DIR / "mitmproxy-ca-cert.cer"


def ca_cert_installed_fresh() -> bool:
    _cert_cache[0] = 0.0
    return ca_cert_installed()


def install_ca_cert() -> tuple[bool, str]:
    """HTTPS フィルタリング用のルート証明書を「現在のユーザー」の信頼済みストアに登録する"""
    p = ca_cert_path()
    if not p.exists():
        return False, "証明書がまだ生成されていません（一度起動してください）"
    if not IS_WIN:
        return False, f"証明書を手動でインストールしてください: {p}"
    r = subprocess.run(["certutil", "-user", "-addstore", "Root", str(p)], capture_output=True,
                       text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode == 0 and ca_cert_installed_fresh():
        return True, "証明書をインストールしました。ブラウザ（Edge）をいったん全部閉じてから開き直してください"
    if r.returncode == 0:
        return False, "証明書の登録がキャンセルされたか、確認できませんでした。もう一度お試しください"
    return False, (r.stdout + r.stderr).strip()[:500]


_cert_cache = [0.0, False]


def ca_cert_installed() -> bool:
    import time
    if time.time() - _cert_cache[0] < 30:
        return _cert_cache[1]
    _cert_cache[0] = time.time()
    _cert_cache[1] = _ca_cert_installed()
    return _cert_cache[1]


def _ca_cert_installed() -> bool:
    if not IS_WIN or not ca_cert_path().exists():
        return False
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        cert = x509.load_pem_x509_certificate((CERT_DIR / "mitmproxy-ca-cert.pem").read_bytes())
        thumb = cert.fingerprint(hashes.SHA1()).hex()
    except Exception:  # noqa: BLE001
        return False
    for args in (["certutil", "-user", "-store", "Root", thumb], ["certutil", "-store", "Root", thumb]):
        r = subprocess.run(args, capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and thumb.lower() in r.stdout.replace(" ", "").lower():
            return True
    return False


def _shoji_named_ca() -> bool:
    return "Shoji" in _ca_subject()


def _ca_subject() -> str:
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate((CERT_DIR / "mitmproxy-ca-cert.pem").read_bytes())
        return cert.subject.rfc4514_string()
    except Exception:  # noqa: BLE001
        return ""


def uninstall_ca_cert() -> tuple[bool, str]:
    if not IS_WIN:
        return False, "Windows 専用の機能です"
    name = "Shoji Local Filtering CA (this PC only)" if _shoji_named_ca() else "mitmproxy"
    r = subprocess.run(["certutil", "-user", "-delstore", "Root", name], capture_output=True,
                       text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0, (r.stdout + r.stderr).strip()[:500]


# ------------------------------------------------------------------ 接続元プロセスの特定
_OWN_STORE_BROWSERS = {"firefox.exe", "librewolf.exe", "waterfox.exe", "floorp.exe", "zen.exe",
                       "thunderbird.exe", "palemoon.exe", "seamonkey.exe"}


def process_for_client(client_port: int, proxy_port: int) -> str:
    """プロキシに接続してきたローカル接続（送信元ポート）を持つプロセス名を返す（Windows のみ）"""
    if not IS_WIN:
        return ""
    import ctypes.wintypes as wt
    iphlp = ctypes.windll.iphlpapi
    size = wt.DWORD(0)
    TCP_TABLE_OWNER_PID_ALL, AF_INET = 5, 2
    iphlp.GetExtendedTcpTable(None, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
    for _ in range(3):
        buf = ctypes.create_string_buffer(size.value + 8192)   # 取得までに接続が増えても入るよう余裕を持たせる
        size = wt.DWORD(len(buf))
        rc = iphlp.GetExtendedTcpTable(buf, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
        if rc == 0:
            break
    else:
        return ""
    n = ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0]
    # MIB_TCPROW_OWNER_PID: state, localAddr, localPort, remoteAddr, remotePort, pid (各 DWORD)
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(wt.DWORD * 6))

    def port(v):
        return ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)
    pid = 0
    for i in range(n):
        r = rows[i]
        if port(r[2]) == client_port and port(r[4]) == proxy_port:
            pid = r[5]
            break
    if not pid:
        return ""
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        name = ctypes.create_unicode_buffer(1024)
        ln = wt.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, name, ctypes.byref(ln)):
            return os.path.basename(name.value).lower()
    finally:
        k32.CloseHandle(h)
    return ""


def is_own_store_browser(proc: str) -> bool:
    return proc in _OWN_STORE_BROWSERS


def enable_firefox_windows_roots() -> int:
    """Firefox に Windows の証明書ストアを使わせる（各プロファイルの user.js に設定を追記）。
    Firefox を再起動すると有効になる。設定したプロファイル数を返す"""
    appdata = os.environ.get("APPDATA")
    if not IS_WIN or not appdata:
        return 0
    from pathlib import Path
    count = 0
    line = 'user_pref("security.enterprise_roots.enabled", true);'
    for base in ("Mozilla/Firefox/Profiles", "Waterfox/Profiles", "librewolf/Profiles", "Floorp/Profiles"):
        root = Path(appdata) / base
        if not root.is_dir():
            continue
        for prof in root.iterdir():
            if not (prof / "prefs.js").exists():
                continue
            uj = prof / "user.js"
            try:
                text = uj.read_text(encoding="utf-8") if uj.exists() else ""
                if "security.enterprise_roots.enabled" not in text:
                    uj.write_text(text + ("\n" if text and not text.endswith("\n") else "")
                                  + "// Shoji: Windows の証明書を信頼する\n" + line + "\n",
                                  encoding="utf-8")
                count += 1
            except OSError:
                continue
    return count


# ------------------------------------------------------------------ 自動起動・多重起動防止
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "Shoji"


def launch_command(*extra: str) -> list[str]:
    """Shoji 自身を起動するコマンド（exe 版 / ソース版のどちらでも）"""
    import sys
    from .config import FROZEN, BASE_DIR
    if FROZEN:
        return [sys.executable, *extra]
    exe = sys.executable
    if IS_WIN and exe.lower().endswith("python.exe"):
        pyw = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(pyw):
            exe = pyw           # コンソール画面を出さない
    return [exe, str(BASE_DIR / "main.py"), *extra]


def get_autostart() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> bool:
    """Windows にサインインしたとき自動で起動する（現在のユーザーのみ・管理者権限不要）"""
    if not IS_WIN:
        return False
    import subprocess as _sp
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            cmd = _sp.list2cmdline(launch_command("--autostart"))
            winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, cmd)
        else:
            _delete_value(k, _RUN_NAME)
    return True


_mutex_handle = None


def acquire_single_instance() -> bool:
    """同時に 2 つ起動しないようにする。既に起動していれば False"""
    global _mutex_handle
    if not IS_WIN:
        return True
    k32 = ctypes.windll.kernel32
    _mutex_handle = k32.CreateMutexW(None, False, "Local\\ShojiAdFilter")
    return k32.GetLastError() != 183   # ERROR_ALREADY_EXISTS


def wait_for_process_exit(pid: int) -> None:
    """指定したプロセスが終了するまで待つ（ウォッチドッグ用）"""
    if IS_WIN:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if not h:
            return
        try:
            k32.WaitForSingleObject(h, 0xFFFFFFFF)
        finally:
            k32.CloseHandle(h)
        return
    import time
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(1)


def open_path(path) -> None:
    """ファイルやフォルダを既定のアプリで開く"""
    if IS_WIN:
        os.startfile(str(path))  # noqa: S606
