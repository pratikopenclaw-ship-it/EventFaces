"""Joining with only the access code (the app's "type the code" path). Same membership
rules as slug+code; the lockout is global (one endpoint covers every event)."""

from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Event, JoinMode, MemberStatus, User


def _join(c: TestClient, code: str):  # type: ignore[no-untyped-def]
    return c.post("/api/join/by-code", json={"code": code})


def test_code_alone_joins_the_right_event(make_user: Callable[..., User], login_as, make_event) -> None:  # type: ignore[no-untyped-def]
    a, b = make_event("Alpha"), make_event("Beta")
    c = login_as(make_user("coder@example.com"))
    r = _join(c, f"  {b.access_code.lower()} ")  # typed loosely: normalized like the web form
    assert r.status_code == 200 and r.json()["id"] == str(b.id)
    assert c.get(f"/api/events/{b.id}").status_code == 200
    assert c.get(f"/api/events/{a.id}").status_code == 403


def test_wrong_codes_lock_out_globally_across_events(make_user, login_as, make_event) -> None:  # type: ignore[no-untyped-def]
    event = make_event("Locked")
    c = login_as(make_user("guesser@example.com"))
    for i in range(get_settings().join_lockout_attempts):
        assert _join(c, f"WRONG{i:03d}").status_code == 400
    assert _join(c, event.access_code).status_code == 429  # even the right code, for any event
    # A different account on the same IP is locked out too (the IP key).
    other = login_as(make_user("guesser2@example.com"))
    assert _join(other, event.access_code).status_code == 429


def test_same_rules_as_slug_join(make_user, login_as, make_event, add_member, db) -> None:  # type: ignore[no-untyped-def]
    invite_only = make_event("Invite", join_mode=JoinMode.invite)
    expired = make_event("Old", access_expires_at=utcnow() - timedelta(hours=1))
    revoked_event = make_event("Revoked")
    u = make_user("rules@example.com")
    add_member(revoked_event, u, status=MemberStatus.revoked)
    c = login_as(u)
    assert _join(c, invite_only.access_code).status_code == 403
    assert _join(c, expired.access_code).status_code == 403
    assert _join(c, revoked_event.access_code).status_code == 403  # never re-approves a revoked member


def test_unverified_and_anonymous_cannot_join(make_user, login_as, make_event) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import new_client

    event: Event = make_event("Gate")
    assert _join(new_client(), event.access_code).status_code == 401
    assert _join(login_as(make_user("unverified-coder@example.com", verified=False)), event.access_code).status_code == 403


def test_code_format_is_bounded(make_user, login_as) -> None:  # type: ignore[no-untyped-def]
    c = login_as(make_user("fmt@example.com"))
    for bad in ["", "ab", "x" * 33, None, 12345678]:
        assert _join(c, bad).status_code == 422  # type: ignore[arg-type]
