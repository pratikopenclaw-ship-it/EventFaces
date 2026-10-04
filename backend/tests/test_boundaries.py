"""Negative and boundary input (Phase C): unicode/RTL/emoji, invalid dates and
timezones, expired tokens, oversized and pathological bodies. Never a 5xx; text
round-trips exactly; limits are enforced with 4xx."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import AuthToken, Event, Invite
from tests.conftest import PASSWORD, FakeMailer, new_client
from tests.test_authz_matrix import World, world  # noqa: F401  (fixture re-export)

TEXTS = [
    "Fête 🎉 in Zürich",
    "حفل الزفاف",  # Arabic (RTL)
    "שמחה \u202eevil\u202c",  # Hebrew + RTL override
    "👨‍👩‍👧‍👦 family 🏳️‍🌈",  # ZWJ sequences
    "á̂̃ combining",
    "𝓯𝓪𝓷𝓬𝔂 𝕥𝕖𝕩𝕥",  # astral plane
    "日本語のイベント",
]


def _admin() -> TestClient:
    c = new_client()
    assert c.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD}).status_code == 200
    return c


@pytest.mark.parametrize("text", TEXTS)
def test_unicode_text_round_trips(text: str, world: World) -> None:  # noqa: F811
    c = _admin()
    r = c.post("/api/events", json={"name": text, "description": text})
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["name"] == text and ev["description"] == text
    got = c.get(f"/api/events/{ev['id']}").json()
    assert got["name"] == text
    assert ev["slug"].isascii() and ev["slug"].replace("-", "").isalnum()


@pytest.mark.parametrize(
    ("body", "ok"),
    [
        ({"name": ""}, False),
        ({"name": "x" * 201}, False),
        ({"name": "x" * 200}, True),
        ({"name": "ok", "description": "d" * 5001}, False),
        ({"name": "ok", "date": "2026-02-30"}, False),
        ({"name": "ok", "date": "2026-13-01"}, False),
        ({"name": "ok", "date": "not-a-date"}, False),
        ({"name": "ok", "access_expires_at": "2026-10-01T10:00:00"}, False),  # no timezone: ambiguous
        ({"name": "ok", "access_expires_at": "2026-10-01T10:00:00+14:00"}, True),
        ({"name": "ok", "access_expires_at": "2026-10-01T10:00:00Z"}, True),
        ({"name": "ok", "access_expires_at": "10000-01-01T00:00:00Z"}, False),
        ({"name": "ok", "join_mode": "everyone"}, False),
    ],
)
def test_event_field_boundaries(body: dict, ok: bool, world: World) -> None:  # noqa: F811
    r = _admin().post("/api/events", json=body)
    assert r.status_code == (201 if ok else 422), r.text[:300]


def test_timezone_offsets_are_normalised(world: World) -> None:  # noqa: F811
    r = _admin().post("/api/events", json={"name": "tz", "access_expires_at": "2026-10-01T10:00:00+14:00"})
    assert r.status_code == 201
    returned = r.json()["access_expires_at"]
    assert returned.endswith(("Z", "+00:00")) and "2026-09-30T20:00:00" in returned


def test_naive_expiry_on_reopened_event_is_rejected_not_500(world: World, db: Session) -> None:  # noqa: F811
    """PATCH on an event whose retention already ran compared a naive client datetime
    with utcnow() (aware) → TypeError → 500."""
    db.execute(update(Event).where(Event.id == world.event_a.id).values(retention_completed_at=utcnow()))
    db.commit()
    r = _admin().patch(f"/api/events/{world.event_a.id}", json={"access_expires_at": "2030-01-01T00:00:00"})
    assert r.status_code == 422, r.text[:300]


def test_member_expiry_requires_timezone(world: World) -> None:  # noqa: F811
    url = f"/api/events/{world.event_a.id}/members/{world.users['attendee_member'].id}"
    c = _admin()
    assert c.patch(url, json={"expires_at": "2030-01-01T00:00:00"}).status_code == 422
    assert c.patch(url, json={"expires_at": "2030-01-01T00:00:00Z"}).status_code == 200


# --- expired tokens --------------------------------------------------------------------


def _expire_all_tokens(db: Session) -> None:
    db.execute(update(AuthToken).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()


def test_expired_verification_link(db: Session, mailer: FakeMailer) -> None:
    c = new_client()
    assert c.post("/api/auth/signup", json={"accept_terms": True, "email": "late@example.com", "password": PASSWORD}).status_code == 202
    token = mailer.last_link_token("late@example.com")
    _expire_all_tokens(db)
    assert c.post("/api/auth/verify-email", json={"token": token}).status_code == 400


def test_expired_reset_link(world: World, db: Session, mailer: FakeMailer) -> None:  # noqa: F811
    c = new_client()
    c.post("/api/auth/forgot-password", json={"email": "member@example.com"})
    token = mailer.last_link_token("member@example.com")
    _expire_all_tokens(db)
    assert c.post("/api/auth/reset-password", json={"token": token, "password": "a-new-password-1"}).status_code == 400
    # the old password still works
    assert new_client().post("/api/auth/login", json={"email": "member@example.com", "password": PASSWORD}).status_code == 200


def test_expired_invite_link(world: World, db: Session, mailer: FakeMailer) -> None:  # noqa: F811
    org = new_client()
    org.post("/api/auth/login", json={"email": "org-this@example.com", "password": PASSWORD})
    assert org.post(f"/api/events/{world.event_a.id}/invites", json={"csv": "slow@example.com"}).status_code == 200
    token = next(m for m in reversed(mailer.outbox) if m.to == "slow@example.com").body.split("/invite/")[1].split()[0]
    db.execute(update(Invite).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    anon = new_client()
    assert anon.get(f"/api/invites/{token}").status_code in (404, 410)
    assert anon.post("/api/invites/register", json={"accept_terms": True, "token": token, "password": PASSWORD}).status_code in (400, 404, 410)
    assert db.scalar(select(Invite.accepted_by).where(Invite.email == "slow@example.com")) is None


def test_expired_session_cookie(world: World, db: Session) -> None:  # noqa: F811
    c = new_client()
    c.post("/api/auth/login", json={"email": "member@example.com", "password": PASSWORD})
    _expire_all_tokens(db)  # refresh token (the session) expired
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/auth/refresh").status_code == 401


# --- oversized / pathological bodies --------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/auth/login", {"email": "a@example.com", "password": "p" * 2_000_000}),
        ("/api/auth/signup", {"accept_terms": True, "email": ("a" * 1_000_000) + "@example.com", "password": PASSWORD}),
        ("/api/removal-requests", {"event": "x", "email": "a@example.com", "message": "m" * 2001}),
        ("/api/join", {"slug": "s" * 81, "code": "ABCDEFGH"}),
    ],
    ids=["2MB-password", "1MB-email", "long-message", "long-slug"],
)
def test_oversized_fields_are_4xx(path: str, body: dict, world: World) -> None:  # noqa: F811
    c = new_client() if "join" not in path else _admin()
    r = c.post(path, json=body)
    assert 400 <= r.status_code < 500, (r.status_code, r.text[:200])


def test_deeply_nested_json_is_rejected_cleanly(world: World) -> None:  # noqa: F811
    depth = 100_000
    payload = ("[" * depth) + ("]" * depth)
    r = new_client().post("/api/auth/login", content=payload.encode(), headers={"content-type": "application/json"})
    assert 400 <= r.status_code < 500, r.status_code


def test_invalid_utf8_body_is_rejected_cleanly(world: World) -> None:  # noqa: F811
    r = new_client().post("/api/auth/login", content=b'{"email": "\xff\xfe", "password": "x"}', headers={"content-type": "application/json"})
    assert 400 <= r.status_code < 500, r.status_code


def test_null_bytes_in_text_fields_do_not_crash(world: World) -> None:  # noqa: F811
    c = _admin()
    r = c.post("/api/events", json={"name": "nul\x00byte", "description": "a\x00b"})
    assert 400 <= r.status_code < 500 or r.status_code == 201, r.status_code  # Postgres text can't hold NUL
    assert r.status_code != 500
