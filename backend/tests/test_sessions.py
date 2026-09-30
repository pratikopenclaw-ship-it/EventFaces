"""Session lifecycle: access tokens die with their session (SEC-021), refresh-token replay
revokes the whole session (SEC-022), and forged/foreign JWTs are rejected."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE, create_access_token
from app.models import User
from tests.conftest import PASSWORD, FakeMailer, new_client


def _login(email: str) -> TestClient:
    c = new_client()
    assert c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c


def _steal(c: TestClient, name: str) -> str:
    value = c.cookies.get(name)
    assert value
    return value


def _client_with(**cookies: str) -> TestClient:
    c = new_client()
    for k, v in cookies.items():
        c.cookies.set(k, v)
    return c


def test_access_token_dies_on_logout(make_user: Callable[..., User]) -> None:
    make_user("s1@example.com")
    victim = _login("s1@example.com")
    stolen = _steal(victim, ACCESS_COOKIE)
    assert victim.post("/api/auth/logout").status_code == 204
    assert _client_with(ef_access=stolen).get("/api/me").status_code == 401


def test_access_token_dies_on_password_reset(make_user: Callable[..., User], mailer: FakeMailer) -> None:
    make_user("s2@example.com")
    attacker = _client_with(ef_access=_steal(_login("s2@example.com"), ACCESS_COOKIE))
    assert attacker.get("/api/me").status_code == 200

    owner = new_client()
    owner.post("/api/auth/forgot-password", json={"email": "s2@example.com"})
    token = mailer.last_link_token("s2@example.com")
    assert owner.post("/api/auth/reset-password", json={"token": token, "password": "a-brand-new-pass"}).status_code == 200
    assert attacker.get("/api/me").status_code == 401


def test_logout_only_ends_that_session(make_user: Callable[..., User]) -> None:
    make_user("s3@example.com")
    laptop, phone = _login("s3@example.com"), _login("s3@example.com")
    assert laptop.post("/api/auth/logout").status_code == 204
    assert phone.get("/api/me").status_code == 200


def test_refresh_keeps_the_session_alive(make_user: Callable[..., User]) -> None:
    make_user("s4@example.com")
    c = _login("s4@example.com")
    for _ in range(3):
        assert c.post("/api/auth/refresh").status_code == 200
        assert c.get("/api/me").status_code == 200


def test_refresh_token_replay_revokes_the_session(make_user: Callable[..., User], monkeypatch: pytest.MonkeyPatch) -> None:
    make_user("s5@example.com")
    victim = _login("s5@example.com")
    old_refresh = _steal(victim, REFRESH_COOKIE)
    assert victim.post("/api/auth/refresh").status_code == 200  # rotates; old token now used

    # Replayed well after the benign cross-tab grace window: treated as theft.
    monkeypatch.setattr(get_settings(), "refresh_reuse_grace_seconds", 0)
    thief = _client_with(ef_refresh=old_refresh)
    assert thief.post("/api/auth/refresh").status_code == 401
    # The whole session family is gone: the victim's current tokens stop working too.
    assert victim.get("/api/me").status_code == 401
    assert victim.post("/api/auth/refresh").status_code == 401


def test_concurrent_refresh_within_grace_does_not_log_out(make_user: Callable[..., User]) -> None:
    """Two tabs refreshing with the same cookie at once must not look like theft."""
    make_user("s6@example.com")
    c = _login("s6@example.com")
    old_refresh = _steal(c, REFRESH_COOKIE)
    assert c.post("/api/auth/refresh").status_code == 200
    assert _client_with(ef_refresh=old_refresh).post("/api/auth/refresh").status_code == 401
    assert c.get("/api/me").status_code == 200
    assert c.post("/api/auth/refresh").status_code == 200


def _forge(payload: dict, key: str | None = None, alg: str = "HS256") -> str:
    return jwt.encode(payload, key if key is not None else get_settings().jwt_secret, algorithm=alg)


def test_forged_and_malformed_access_tokens_are_rejected(make_user: Callable[..., User]) -> None:
    u: User = make_user("s7@example.com")
    now = datetime.now(UTC)
    good = {"sub": str(u.id), "role": "super_admin", "type": "access", "iat": now, "exp": now + timedelta(minutes=5)}
    header_none = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"
    unsigned = header_none + "." + jwt.encode(good, "x", algorithm="HS256").split(".")[1] + "."
    cases = {
        "alg-none": unsigned,
        "wrong-key": _forge(good, key="not-the-server-secret-but-long-enough-000"),
        "no-sid": _forge(good),  # correctly signed but not bound to any session
        "random-sid": _forge({**good, "sid": str(uuid.uuid4())}),
        "expired": _forge({**good, "exp": now - timedelta(seconds=1)}),
        "wrong-type": _forge({**good, "type": "download"}),
        "bad-sub": _forge({**good, "sub": "not-a-uuid"}),
        "garbage": "a.b.c",
        "legacy-helper": create_access_token(u.id, "attendee"),
    }
    for name, token in cases.items():
        r = _client_with(ef_access=token).get("/api/me")
        assert r.status_code == 401, (name, r.status_code, r.text)
