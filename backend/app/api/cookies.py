import secrets

from fastapi import Response

from app.core.config import get_settings
from app.core.security import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    s = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=s.access_token_minutes * 60,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


def set_csrf_cookie(response: Response) -> str:
    """Double-submit CSRF token: readable by JS, echoed back in the X-CSRF-Token header."""
    token = secrets.token_urlsafe(24)
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        secure=get_settings().cookie_secure,
        samesite="strict",
        path="/",
    )
    return token
