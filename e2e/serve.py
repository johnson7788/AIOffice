#!/usr/bin/env python3
"""Host test harness mirroring frontend/nginx.conf for e2e (no Docker needed).

Serves the 4 built SPA dists on one origin and reverse-proxies the API prefixes
to the backend, exactly like the production nginx config. ponytail: stdlib only,
this is a TEST harness — real deploy uses frontend/nginx.conf + Dockerfile.

Usage: python3 serve.py [PORT]   (PORT default 8080)
Env:   BACKEND (default http://127.0.0.1:8585), DIST_ROOT (built dists parent)
"""
import os
import sys
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
BACKEND = os.environ.get("BACKEND", "http://127.0.0.1:8585")
ROOT = os.environ.get("DIST_ROOT", "/tmp/aioffice-web/html")

API_PREFIXES = ("/ai", "/auth", "/documents", "/projects", "/gallery", "/files", "/share", "/healthz")
SPA_APPS = ("slides", "pdf", "markdown", "sheets")  # served under /<app>/; docs is served at /
# The sheets SPA lives at /sheets/ but the xlsx sidecar API also hangs off
# /sheets/* — mirror nginx.conf: only the fixed endpoint set is API. ponytail:
# keep in sync with backend/app/routers/sheets.py.
SHEETS_API = (
    "open", "read-range", "read-formulas", "read-media", "recalc",
    "manifest", "read-entries", "scan-entries", "save", "close",
)
MIME = {
    ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
    ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
    ".woff2": "font/woff2", ".wasm": "application/wasm", ".map": "application/json",
    ".mjs": "text/javascript",  # pdf.js worker is a module — octet-stream breaks it
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _is_api(self):
        p = self.path.split("?", 1)[0]
        for pre in API_PREFIXES:
            if p == pre or p.startswith(pre + "/") or p.startswith(pre + "?"):
                return True
        if p.startswith("/sheets/"):
            seg = p[len("/sheets/"):].split("/", 1)[0].split("?", 1)[0]
            if seg in SHEETS_API:
                return True
        return False

    def _proxy(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(BACKEND + self.path, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length", "connection"):
                req.add_header(k, v)
        try:
            # Stream the upstream body through as it arrives (mirrors nginx
            # proxy_buffering off) — /ai/stream is a long-lived SSE feed the
            # renderer's silence watchdog depends on; buffering would starve it.
            with urllib.request.urlopen(req, timeout=600) as r:
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection", "content-length", "content-type"):
                        self.send_header(k, v)
                self.send_header("Content-Type", r.headers.get("Content-Type", "application/octet-stream"))
                self.send_header("Connection", "close")  # no CL → client reads until EOF
                self.end_headers()
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:  # forward the backend's error status verbatim
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: BLE001
            msg = str(e).encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def _resolve_file(self):
        p = self.path.split("?", 1)[0]
        for app in SPA_APPS:
            if p == f"/{app}" or p == f"/{app}/":
                return os.path.join(ROOT, app, "index.html")
            if p.startswith(f"/{app}/"):
                cand = os.path.join(ROOT, app, p[len(app) + 2 :])
                return cand if os.path.isfile(cand) else os.path.join(ROOT, app, "index.html")
        # default app (docs) at root, SPA fallback to its index.html
        cand = os.path.join(ROOT, "docs", p.lstrip("/"))
        return cand if os.path.isfile(cand) else os.path.join(ROOT, "docs", "index.html")

    def _static(self):
        path = self._resolve_file()
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ext = os.path.splitext(path)[1]
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _route(self):
        if self._is_api():
            self._proxy()
        else:
            self._static()

    do_GET = _route
    do_HEAD = _route
    do_POST = _route
    do_PUT = _route
    do_DELETE = _route
    do_PATCH = _route

    def log_message(self, *a):  # quiet
        pass


if __name__ == "__main__":
    print(f"serving {ROOT} on :{PORT}, proxying {API_PREFIXES} -> {BACKEND}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
