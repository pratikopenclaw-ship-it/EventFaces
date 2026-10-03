import secrets

from fastapi import Response

from app.core.config import get_settings
from app.core.security import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, THEME_COOKIE
from app.models.enums import ThemePreference


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


def set_theme_cookie(response: Response, theme: ThemePreference) -> None:
    """Mirror the profile's theme so the next page renders in it with no flash (and on other devices after login)."""
    response.set_cookie(
        THEME_COOKIE,
        theme.value,
        max_age=365 * 86400,
        httponly=False,  # the theme switcher updates it in the browser too
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )
