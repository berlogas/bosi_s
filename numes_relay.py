#!/usr/bin/env python3
"""Локальный релей opencode -> Numes: прямое соединение без системных прокси, потоковый SSE."""
import sys
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://api.numes.ai"
PORT = 8787
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
       "te", "trailers", "transfer-encoding", "upgrade",
       "content-encoding", "content-length", "host"}

# ProxyHandler({}) = не использовать никаких прокси, соединяться напрямую
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

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
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["Accept-Encoding"] = "identity"   # просим несжатый ответ
        req = urllib.request.Request(UPSTREAM + self.path, data=body,
                                     headers=headers, method=self.command)
        try:
            r = OPENER.open(req, timeout=600)
        except urllib.error.HTTPError as e:
            self._fail(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
            return
        except Exception as e:
            self._fail(502, ('{"error":{"message":"relay: %s"}}' % e).encode())
            return

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
            for line in r:                      # построчно = мгновенный проброс SSE
                try:
                    self.wfile.write(line)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break

    do_GET = do_POST = do_HEAD = _relay

if __name__ == "__main__":
    print("Обнаружены системные прокси:", urllib.request.getproxies(), flush=True)
    print(f"Numes relay (напрямую, без прокси): http://127.0.0.1:{PORT} -> {UPSTREAM}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Relay).serve_forever()