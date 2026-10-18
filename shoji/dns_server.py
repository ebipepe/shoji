# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The Shoji Authors
"""DNS フィルタリングサーバー。

PC（や同じ LAN のスマホ等）の DNS をこのサーバーに向けると、ブラウザ以外のアプリも含め
広告・トラッカーのドメインへの接続を名前解決の段階で止められる（アプリ内広告のブロック）。
上流へは DNS-over-HTTPS で問い合わせるので、通信経路での盗み見も防げる。
"""
from __future__ import annotations

import http.client
import socket
import socketserver
import ssl
import struct
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from dnslib import AAAA, QTYPE, RCODE, RR, A, DNSRecord

from .config import is_whitelisted
from .context import AppContext


class Upstream:
    """上流 DNS（DoH または通常の UDP）。DoH は接続をスレッドごとに使い回す。"""

    def __init__(self, primary: str, fallback: str):
        self.primary = primary
        self.fallback = fallback
        self._local = threading.local()

    def _doh(self, url: str, wire: bytes, timeout: float = 4.0) -> bytes:
        u = urlsplit(url)
        key = (u.hostname, u.port)
        conn = getattr(self._local, "conns", {}).get(key)
        for attempt in range(2):
            if conn is None:
                conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout,
                                                   context=ssl.create_default_context())
                self._local.__dict__.setdefault("conns", {})[key] = conn
            try:
                conn.request("POST", u.path or "/dns-query", body=wire, headers={
                    "Content-Type": "application/dns-message", "Accept": "application/dns-message"})
                r = conn.getresponse()
                body = r.read()
                if r.status != 200:
                    raise OSError(f"DoH HTTP {r.status}")
                return body
            except (OSError, http.client.HTTPException):
                conn.close()
                conn = None
                self._local.conns.pop(key, None)
                if attempt:
                    raise
        raise OSError("DoH failed")

    @staticmethod
    def _udp(server: str, wire: bytes, timeout: float = 3.0) -> bytes:
        host, _, port = server.partition(":") if server.count(":") == 1 else (server, "", "")
        fam = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(fam, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(wire, (host, int(port or 53)))
            data, _ = s.recvfrom(65535)
            return data

    def query(self, wire: bytes) -> bytes:
        for server in (self.primary, self.fallback):
            if not server:
                continue
            try:
                if server.startswith("https://"):
                    return self._doh(server, wire)
                return self._udp(server, wire)
            except Exception:  # noqa: BLE001 — 次の上流で再試行
                continue
        raise OSError("all upstream DNS servers failed")


class DnsFilter:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        dcfg = ctx.cfg["dns"]
        self.upstream = Upstream(dcfg["upstream"], dcfg.get("fallback_upstream", ""))
        self.cache: OrderedDict = OrderedDict()
        self.cache_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=32, thread_name_prefix="dns")
        self.servers: list = []

    # ------------------------------------------------------------ 応答の生成
    def _blocked_reply(self, req: DNSRecord) -> bytes:
        reply = req.reply()
        q = req.q
        mode = self.ctx.cfg["dns"].get("block_response", "zero")
        if mode == "nxdomain":
            reply.header.rcode = RCODE.NXDOMAIN
        elif q.qtype == QTYPE.A:
            reply.add_answer(RR(q.qname, QTYPE.A, rdata=A("0.0.0.0"), ttl=300))
        elif q.qtype == QTYPE.AAAA:
            reply.add_answer(RR(q.qname, QTYPE.AAAA, rdata=AAAA("::"), ttl=300))
        # それ以外の種別 (HTTPS/SVCB 等) は空の応答
        return reply.pack()

    def _cache_get(self, key):
        with self.cache_lock:
            item = self.cache.get(key)
            if not item:
                return None
            exp, data = item
            if exp < time.time():
                self.cache.pop(key, None)
                return None
            self.cache.move_to_end(key)
            return data

    def _cache_put(self, key, data: bytes, rec: DNSRecord):
        ttls = [rr.ttl for rr in rec.rr] or [60]
        ttl = max(10, min(min(ttls), 3600))
        with self.cache_lock:
            self.cache[key] = (time.time() + ttl, data)
            limit = self.ctx.cfg["dns"].get("cache_size", 5000)
            while len(self.cache) > limit:
                self.cache.popitem(last=False)

    def resolve(self, wire: bytes, client: str = "") -> bytes:
        try:
            req = DNSRecord.parse(wire)
        except Exception:  # noqa: BLE001
            return b""
        if not req.questions:
            return req.reply().pack()
        q = req.q
        name = str(q.qname).rstrip(".").lower()
        stats = self.ctx.stats
        stats.count_request("dns")
        cfg = self.ctx.cfg
        F = cfg["features"]
        allowed = (self.ctx.paused or is_whitelisted(name, cfg.get("whitelist", []))
                   or self.ctx.is_allowed(name))

        if F.get("dns_filtering", True) and not allowed:
            cat = self.ctx.engine.dns_lookup(name)
            if cat and ((cat == "ad" and F["block_ads"]) or (cat == "tracker" and F["block_trackers"])):
                stats.record(cat, "dns", name, "dns", detail=f"{QTYPE.get(q.qtype)} from {client}")
                return self._blocked_reply(req)

        key = (name, q.qtype, q.qclass)
        cached = self._cache_get(key)
        if cached:
            return struct.pack("!H", req.header.id) + cached[2:]
        try:
            # 上流には ID=0 で問い合わせる（応答をキャッシュで使い回すため）
            data = self.upstream.query(b"\x00\x00" + wire[2:])
            rec = DNSRecord.parse(data)
        except Exception:  # noqa: BLE001
            reply = req.reply()
            reply.header.rcode = RCODE.SERVFAIL
            return reply.pack()

        # CNAME クローキング対策: 1st パーティのサブドメインに偽装したトラッカーを検出
        if F.get("cname_uncloaking", True) and F.get("dns_filtering", True) and not allowed:
            for rr in rec.rr:
                if rr.rtype == QTYPE.CNAME:
                    target = str(rr.rdata).rstrip(".").lower()
                    cat = self.ctx.engine.dns_lookup(target)
                    if cat and F["block_trackers"]:
                        stats.record("tracker", "dns", name, "dns", detail=f"CNAME 偽装 → {target}")
                        return self._blocked_reply(req)
        if rec.header.rcode == RCODE.NOERROR:
            self._cache_put(key, data, rec)
        return struct.pack("!H", req.header.id) + data[2:]

    # ------------------------------------------------------------ サーバー
    def start(self) -> list[str]:
        dcfg = self.ctx.cfg["dns"]
        host, port = dcfg["listen_host"], int(dcfg["listen_port"])
        hosts = [host]
        if host == "127.0.0.1":
            hosts.append("::1")
        elif host == "0.0.0.0":
            hosts.append("::")
        started, errors = [], []
        for h in hosts:
            for kind in ("udp", "tcp"):
                try:
                    srv = self._make_server(kind, h, port)
                except OSError as e:
                    errors.append(f"{kind}/{h}:{port}: {e}")
                    continue
                t = threading.Thread(target=srv.serve_forever, name=f"dns-{kind}-{h}", daemon=True)
                t.start()
                self.servers.append(srv)
                started.append(f"{kind}://[{h}]:{port}" if ":" in h else f"{kind}://{h}:{port}")
        if not started:
            raise OSError("DNS サーバーを起動できません: " + "; ".join(errors))
        return started

    def _make_server(self, kind: str, host: str, port: int):
        flt = self
        fam = socket.AF_INET6 if ":" in host else socket.AF_INET

        class UDPHandler(socketserver.BaseRequestHandler):
            def handle(self):
                data, sock = self.request
                addr = self.client_address
                flt.pool.submit(self._answer, data, sock, addr)

            @staticmethod
            def _answer(data, sock, addr):
                out = flt.resolve(data, addr[0])
                if out:
                    try:
                        sock.sendto(out, addr)
                    except OSError:
                        pass

        class TCPHandler(socketserver.BaseRequestHandler):
            def handle(self):
                conn = self.request
                conn.settimeout(10)
                try:
                    while True:
                        hdr = conn.recv(2)
                        if len(hdr) < 2:
                            return
                        ln = struct.unpack("!H", hdr)[0]
                        buf = b""
                        while len(buf) < ln:
                            chunk = conn.recv(ln - len(buf))
                            if not chunk:
                                return
                            buf += chunk
                        out = flt.resolve(buf, self.client_address[0])
                        conn.sendall(struct.pack("!H", len(out)) + out)
                except OSError:
                    return

        # UDP は受信 1 スレッド＋処理はスレッドプールで並列化、TCP は接続ごとにスレッド
        base = socketserver.UDPServer if kind == "udp" else socketserver.ThreadingTCPServer

        class Server(base):
            address_family = fam
            allow_reuse_address = False
            daemon_threads = True

        return Server((host, port), UDPHandler if kind == "udp" else TCPHandler)

    def stop(self):
        for s in self.servers:
            try:
                s.shutdown()
                s.server_close()
            except OSError:
                pass
        self.pool.shutdown(wait=False)
