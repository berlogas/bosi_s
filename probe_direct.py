#!/usr/bin/env python3
"""Numes relay v3: IPv4-only, без прокси, самопроверка при старте, лог по стадиям."""
import socket, ssl, sys, time, http.client, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://api.numes.ai"
PORT = 8787
TIMEOUT = 120
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
       "trailers", "transfer-encoding", "upgrade", "content-encoding", "content-length", "host"}

class IPv4HTTPSConnection(http.client.HTTPSConnection):
    """Только IPv4 — исключает зависание на битом/чёрном дырявом IPv6."""
    def connect(self):
        last = None
        for res in socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM):
            af, st, proto, _, sa = res
            try:
                s = socket.socket(af, st, proto)
                s.settimeout(self.timeout)
                s.connect(sa)
                ctx = self._context or ssl.create_default_context()
                self.sock = ctx.wrap_socket(s, server_hostname=self.host)
                return
            except OSError as e:
                last = e
        raise last or OSError(f"no IPv4 route to {self.host}")

class IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        ctx = self._context or ssl.create_default_context()
        return self.do_open(IPv4HTTPSConnection, req, context=ctx)

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), IPv4HTTPSHandler())

def self_test():
    print("[self-test] прямое соединение с", UPSTREAM, "...", flush=True)
    t0 = time.time()
    try:
        r = OPENER.open(UPSTREAM + "/api/v1/models", timeout=30)
        print(f"[self-test] OK: HTTP {r.status} за {time.time()-t0:.1f} с", flush=True)
    except urllib.error.HTTPError as e:
        print(f"[self-test] OK (канал есть): HTTP {e.code} за {time.time()-t0:.1f} с", flush=True)
    except Exception as e:
        print(f"[self-test] FAIL: {type(e).__name__}: {e} — Numes недоступен прямо сейчас, дело не в релее", flush=True)

class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[relay] " + (fmt % args) + "\n")

    def _fail(self, code, payload, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _relay(self):
        t0 = time.time()
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        self.log_message("%s %s (%d bytes) -> соединяюсь...", self.command, self.path, n)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["Accept-Encoding"] = "identity"
        req = urllib.request.Request(UPSTREAM + self.path, data=body,
                                     headers=headers, method=self.command)
        try:
            r = OPENER.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            self.log_message("%s %s -> HTTP %d за %.1f с", self.command, self.path, e.code, time.time() - t0)
            self._fail(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
            return
        except Exception as e:
            self.log_message("%s %s -> %s: %s (%.1f с)", self.command, self.path,
                             type(e).__name__, e, time.time() - t0)
            self._fail(502, ('{"error":{"message":"relay: %s: %s"}}' % (type(e).__name__, e)).encode())
            return
        self.log_message("%s %s -> HTTP %d за %.1f с, стримлю...", self.command, self.path,
                         r.status, time.time() - t0)
        with r:
            self.send_response(r.status)
            for k, v in r.headers.items():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command == "HEAD":
                return
            sent = 0
            for line in r:
                try:
                    self.wfile.write(line)
                    self.wfile.flush()
                    sent += len(line)
                except (BrokenPipeError, ConnectionResetError):
                    break
            self.log_message("%s %s завершено: %d bytes за %.1f с", self.command, self.path,
                             sent, time.time() - t0)

    do_GET = do_POST = do_HEAD = _relay

if __name__ == "__main__":
    print("Прокси, которые видит Python:", urllib.request.getproxies(), flush=True)
    self_test()
    print(f"Relay: http://127.0.0.1:{PORT} -> {UPSTREAM} (IPv4-only, без прокси)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Relay).serve_forever()