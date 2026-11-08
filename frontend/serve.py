"""Serve the web client and relay its API requests to the separate backend."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ASSETS = {"/": ("index.html","text/html; charset=utf-8"),
          "/markdown-it.min.js": ("markdown-it.min.js","text/javascript; charset=utf-8"),
          "/workspace.js": ("workspace.js","text/javascript; charset=utf-8"),
          "/TripSci-icon.png": ("TripSci-icon.png","image/png")}
API = {"/v1/state", "/v1/action"}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, mime, body):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.partition("?")[0]
        if path in ASSETS:
            name,mime = ASSETS[path]
            self.respond(200,mime,Path(__file__).with_name(name).read_bytes())
        else:
            self.proxy()

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise ValueError
        except ValueError:
            return self.respond(400, "application/json", b'{"error":"Invalid request size"}')
        if self.headers.get_content_type() != "application/json":
            return self.respond(415, "application/json", b'{"error":"Expected JSON"}')
        self.proxy(self.rfile.read(size))

    def proxy(self, data=None):
        if self.path not in API:
            return self.respond(404, "application/json", b'{"error":"Not found"}')
        timeout = 10
        if data is not None:
            try:
                request = json.loads(data)
                if isinstance(request, dict) and request.get("op") == "message":
                    timeout = 95
            except (ValueError, UnicodeError):
                pass
        try:
            with urlopen(Request(self.server.backend+self.path, data=data,
                         headers={"Content-Type":"application/json"}), timeout=timeout) as r:
                self.respond(r.status, r.headers["Content-Type"], r.read())
        except HTTPError as exc:
            self.respond(exc.code, exc.headers["Content-Type"], exc.read())
        except (URLError, TimeoutError):
            self.respond(502, "application/json", b'{"error":"Backend unavailable"}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--backend-port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.backend = f"http://127.0.0.1:{args.backend_port}"
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()
