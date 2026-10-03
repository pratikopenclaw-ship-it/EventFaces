"""Minimum supported app version (force an update after a security fix).

Every app request (bearer header, or the mobile sign-in endpoints) must send
`X-App-Version: MAJOR.MINOR.PATCH`; below IOS_MIN_SUPPORTED_VERSION, or missing, the API
answers 426 before doing anything else. Browsers never send either, so web is unaffected."""

import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.csrf import MOBILE_AUTH_PREFIX
from app.core.config import get_settings

VERSION_HEADER = "x-app-version"
_SEMVER = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
EXEMPT = {"/api/app/config", "/api/health"}


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    m = _SEMVER.match(value or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_app_request(request: Request) -> bool:
    return "authorization" in request.headers or request.url.path.startswith(MOBILE_AUTH_PREFIX)


class AppVersionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/api/") and request.url.path not in EXEMPT and is_app_request(request):
            s = get_settings()
            version = parse_version(request.headers.get(VERSION_HEADER))
            minimum = parse_version(s.ios_min_supported_version)
            if version is None or minimum is None or version < minimum:
                return JSONResponse(
                    {"detail": "update_required", "min_supported_version": s.ios_min_supported_version, "update_url": s.ios_update_url},
                    status_code=426,
                )
        return await call_next(request)
