"""Theme preference (light/dark/system) and per-event accent colours.

The theme is mirrored into the non-httpOnly `ef_theme` cookie, which the Next.js server
reads to render `<html data-theme>`: only the three allowed values may ever be stored
or echoed. Accent colours end up in a style attribute, so only `#rrggbb` is accepted."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models import Event, MemberRole, ThemePreference, User, UserRole
from tests.conftest import PASSWORD, new_client

BAD_THEMES = ["purple", "", "Dark", "SYSTEM", " dark", "dark;", "<script>", "light\r\nSet-Cookie: x=1", 1, None, ["dark"]]
BAD_ACCENTS = ["red", "#fff", "#gggggg", "#1234567", "1a7f74", "javascript:alert(1)", "#1a7f7;", "url(x)", "#1a7f74 !important", 123]


def _theme_cookie(r) -> str:  # type: ignore[no-untyped-def]
    headers = [h for h in r.headers.get_list("set-cookie") if h.startswith("ef_theme=")]
    assert len(headers) == 1, r.headers.get_list("set-cookie")
    return headers[0]


def test_theme_defaults_to_system(make_user: Callable[..., User], login_as: Callable[[User], TestClient]) -> None:
    c = login_as(make_user("theme-default@example.com"))
    assert c.get("/api/me").json()["theme"] == "system"


@pytest.mark.parametrize("theme", ["light", "dark", "system"])
def test_preference_is_saved_and_mirrored_in_a_lax_cookie(
    theme: str, make_user: Callable[..., User], login_as: Callable[[User], TestClient], db: Session
) -> None:
    u = make_user(f"theme-{theme}@example.com")
    c = login_as(u)
    r = c.patch("/api/me/preferences", json={"theme": theme})
    assert r.status_code == 200 and r.json()["theme"] == theme
    cookie = _theme_cookie(r)
    assert cookie.startswith(f"ef_theme={theme};")
    assert "samesite=lax" in cookie.lower() and "path=/" in cookie.lower()
    assert "httponly" not in cookie.lower()  # the switcher updates it client-side too
    db.refresh(u)
    assert u.theme == ThemePreference(theme)


@pytest.mark.parametrize("bad", BAD_THEMES, ids=repr)
def test_preference_accepts_only_the_three_values(
    bad: object, make_user: Callable[..., User], login_as: Callable[[User], TestClient], db: Session
) -> None:
    u = make_user("theme-bad@example.com")
    c = login_as(u)
    c.patch("/api/me/preferences", json={"theme": "dark"})
    r = c.patch("/api/me/preferences", json={"theme": bad})
    assert r.status_code == 422
    assert not [h for h in r.headers.get_list("set-cookie") if h.startswith("ef_theme=")]
    db.refresh(u)
    assert u.theme == ThemePreference.dark


def test_preference_requires_login_and_csrf(make_user: Callable[..., User], login_as: Callable[[User], TestClient]) -> None:
    assert new_client().patch("/api/me/preferences", json={"theme": "dark"}).status_code == 401
    c = login_as(make_user("theme-csrf@example.com"))
    del c.headers["X-CSRF-Token"]
    assert c.patch("/api/me/preferences", json={"theme": "dark"}).status_code == 403


def test_login_and_refresh_carry_the_profile_theme_to_other_devices(
    make_user: Callable[..., User], login_as: Callable[[User], TestClient]
) -> None:
    u = make_user("theme-sync@example.com")
    login_as(u).patch("/api/me/preferences", json={"theme": "dark"})
    other = new_client()  # a second device with no theme cookie
    r = other.post("/api/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["theme"] == "dark"
    assert _theme_cookie(r).startswith("ef_theme=dark;")
    r = other.post("/api/auth/refresh")
    assert r.status_code == 200 and _theme_cookie(r).startswith("ef_theme=dark;")


def test_database_rejects_other_theme_values(db: Session, make_user: Callable[..., User]) -> None:
    u = make_user("theme-db@example.com")
    with pytest.raises(DataError):
        db.execute(text("UPDATE users SET theme = 'purple' WHERE id = :id"), {"id": u.id})
    db.rollback()


def _organizer(make_user, login_as, make_event, add_member) -> tuple[Event, TestClient]:  # type: ignore[no-untyped-def]
    org = make_user("accent-org@example.com", role=UserRole.organizer)
    event = make_event("Accent Party")
    add_member(event, org, role=MemberRole.organizer)
    return event, login_as(org)


def test_accent_color_is_normalised_shown_to_attendees_and_clearable(
    make_user, login_as, make_event, add_member  # type: ignore[no-untyped-def]
) -> None:
    event, org = _organizer(make_user, login_as, make_event, add_member)
    r = org.patch(f"/api/events/{event.id}", json={"accent_color": "#1A7F74"})
    assert r.status_code == 200 and r.json()["accent_color"] == "#1a7f74"
    attendee = make_user("accent-att@example.com")
    add_member(event, attendee)
    assert login_as(attendee).get(f"/api/events/{event.id}").json()["accent_color"] == "#1a7f74"
    assert org.patch(f"/api/events/{event.id}", json={"accent_color": ""}).json()["accent_color"] is None


@pytest.mark.parametrize("bad", BAD_ACCENTS, ids=repr)
def test_accent_color_accepts_only_hex(bad: object, make_user, login_as, make_event, add_member) -> None:  # type: ignore[no-untyped-def]
    event, org = _organizer(make_user, login_as, make_event, add_member)
    assert org.patch(f"/api/events/{event.id}", json={"accent_color": bad}).status_code == 422
    admin = login_as(make_user("accent-admin@example.com", role=UserRole.super_admin))
    assert admin.post("/api/events", json={"name": "X", "accent_color": bad}).status_code == 422


def test_database_rejects_malformed_accent(db: Session, make_event) -> None:  # type: ignore[no-untyped-def]
    event = make_event("Accent DB")
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE events SET accent_color = 'red;x' WHERE id = :id"), {"id": event.id})
    db.rollback()
