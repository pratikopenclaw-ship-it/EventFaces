"""Authenticating reverse proxy for DAST (local stack only).

ZAP's OpenAPI scan sends no cookies, and its replacer only rewrites headers that exist,
so an "authenticated" scan silently ran unauthenticated. This proxy logs in as a
dedicated scan user and injects the session cookie + CSRF header into every request
before forwarding to the API. Usage (inside the compose network):
    python zap_auth_proxy.py http://api:8000 <email> <password>            # web: cookie + CSRF
    python zap_auth_proxy.py http://api:8000 <email> - bearer              # iOS app: bearer token

Bearer mode signs in like the app (emailed code, read from the e2e server's captured
mail, and a fresh P-256 device key) and re-signs-in before the 15-minute token expires.
Needs the e2e API (docker-compose.e2e.yml) for /__e2e/mail.
"""

import base64
import http.server
import socketserver
import sys
import threading
import time
import urllib.request

import httpx

UPSTREAM, EMAIL, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]
MODE = sys.argv[4] if len(sys.argv) > 4 else "cookie"
HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "host", "content-encoding"}


def login() -> tuple[str, str]:
    c = httpx.Client(base_url=UPSTREAM)
    csrf = c.get("/api/auth/csrf").json()["csrf_token"]
    r = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"x-csrf-token": csrf})
    r.raise_for_status()
    return "; ".join(f"{k}={v}" for k, v in c.cookies.items()), csrf


def bearer_login() -> str:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    c = httpx.Client(base_url=UPSTREAM, headers={"X-App-Version": "1.0.0"})
    c.post("/api/mobile/auth/code/request", json={"email": EMAIL}).raise_for_status()
    code = c.get("/__e2e/mail", params={"to": EMAIL}).json()["subject"].split()[0]
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    r = c.post("/api/mobile/auth/code/verify", json={"email": EMAIL, "code": code, "device": {"name": "ZAP", "public_key": base64.b64encode(key).decode()}})
    r.raise_for_status()
    return r.json()["access_token"]


_lock = threading.Lock()
_auth: dict[str, object] = {}


def auth_headers() -> dict[str, str]:
    with _lock:
        if MODE == "bearer":
            if time.time() - float(_auth.get("at", 0)) > 600:  # tokens live 15 min
                _auth.update(token=bearer_login(), at=time.time())
            return {"Authorization": f"Bearer {_auth['token']}", "X-App-Version": "1.0.0"}
        if "cookie" not in _auth:
            _auth["cookie"], _auth["csrf"] = login()
        return {"Cookie": str(_auth["cookie"]), "X-CSRF-Token": str(_auth["csrf"])}


# Session-ending endpoints are not forwarded in an authenticated scan (the usual DAST
# "exclude logout" rule): a fuzzed logout would end the scan's session and silently turn
# the rest of the scan unauthenticated. They are covered by the unauthenticated scan and
# the test suite.
SESSION_ENDING = {("POST", "/api/auth/logout"), ("POST", "/api/mobile/auth/logout")}
_stats: dict[str, int] = {}


def _count(key: str) -> None:
    with _lock:
        _stats[key] = _stats.get(key, 0) + 1
        if sum(_stats.values()) % 250 == 0:
            print("status mix:", dict(sorted(_stats.items())), flush=True)


def _send(method: str, path: str, body: bytes | None, base_headers: dict[str, str]):  # type: ignore[no-untyped-def]
    headers = dict(base_headers)
    headers.update(auth_headers())
    req = urllib.request.Request(UPSTREAM + path, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=60)  # noqa: S310 - fixed local upstream
        return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


class Handler(http.server.BaseHTTPRequestHandler):
    def _forward(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else None
        if (self.command, self.path.split("?")[0]) in SESSION_ENDING:
            _count("excluded")
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP | {"cookie", "authorization"}}
        try:
            status, rheaders, data = _send(self.command, self.path, body, headers)
        except Exception:  # noqa: BLE001 - e.g. sign-in refused: must show up in the mix, not vanish
            _count("proxy-error")
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        # A 401 is usually the endpoint's own answer (e.g. a fuzzed refresh token). Sign in
        # again only if the scan's session really ended, or the sign-in rate limits would lock
        # the proxy out and the rest of the scan would never reach the API.
        if status == 401 and _send("GET", "/api/me", None, {})[0] == 401:
            with _lock:
                _auth.clear()
            status, rheaders, data = _send(self.command, self.path, body, headers)
            _count("401-session-renewed")
        _count(str(status))
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
