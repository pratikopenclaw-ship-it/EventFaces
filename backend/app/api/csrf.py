from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE, constant_time_equals

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# The app's pre-login endpoints: they read and set no cookies, so there is nothing for a
# cross-site request to ride on (their abuse limits are rate limits and lockouts).
MOBILE_AUTH_PREFIX = "/api/mobile/auth/"


def cookieless_app_request(request: Request) -> bool:
    """A request the CSRF check doesn't apply to: it carries no auth cookie and either an
    Authorization header (which a cross-site page can't add: CORS is not enabled) or it
    targets the cookie-free mobile sign-in endpoints."""
    if ACCESS_COOKIE in request.cookies or REFRESH_COOKIE in request.cookies:
        return False
    return "authorization" in request.headers or request.url.path.startswith(MOBILE_AUTH_PREFIX)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject state-changing API requests unless the CSRF header matches the cookie."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and not cookieless_app_request(request)
        ):
            cookie = request.cookies.get(CSRF_COOKIE)
            header = request.headers.get(CSRF_HEADER)
            if not cookie or not header or not constant_time_equals(cookie, header):
                return JSONResponse({"detail": "CSRF check failed"}, status_code=403)
        return await call_next(request)
