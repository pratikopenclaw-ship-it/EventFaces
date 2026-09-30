"""Authenticating reverse proxy for DAST (local stack only).

ZAP's OpenAPI scan sends no cookies, and its replacer only rewrites headers that exist,
so an "authenticated" scan silently ran unauthenticated. This proxy logs in as a
dedicated scan user and injects the session cookie + CSRF header into every request
before forwarding to the API. Usage (inside the compose network):
    python zap_auth_proxy.py http://api:8000 <email> <password>
"""

import http.server
import socketserver
import sys
import urllib.request

import httpx

UPSTREAM, EMAIL, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]
HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "host", "content-encoding"}


def login() -> tuple[str, str]:
    c = httpx.Client(base_url=UPSTREAM)
    csrf = c.get("/api/auth/csrf").json()["csrf_token"]
    r = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"x-csrf-token": csrf})
    r.raise_for_status()
    return "; ".join(f"{k}={v}" for k, v in c.cookies.items()), csrf


COOKIE, CSRF = login()


class Handler(http.server.BaseHTTPRequestHandler):
    def _forward(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["Cookie"] = COOKIE
        headers["X-CSRF-Token"] = CSRF
        req = urllib.request.Request(UPSTREAM + self.path, data=body, headers=headers, method=self.command)
        try:
            resp = urllib.request.urlopen(req, timeout=60)  # noqa: S310 - fixed local upstream
            status, rheaders, data = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, rheaders, data = e.code, e.headers, e.read()
        self.send_response(status)
        for k, v in rheaders.items():
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _forward

    def log_message(self, *args: object) -> None:
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    print("auth proxy ready", flush=True)
    Server(("0.0.0.0", 8080), Handler).serve_forever()
