"""SEC-041: Argon2 hashing costs ~64 MiB and real CPU per call. Found by the 10x burst
load test: 60 concurrent logins pushed the API from 0.7 to 2.4 GB and exhausted the DB
pool (hashing ran while a pooled connection was checked out), so unrelated requests 500'd.
No account is needed: ~40 wrong-password logins from one IP fit the rate limits.

Invariants: no password hashing while holding a DB connection; at most
PASSWORD_HASH_MAX_CONCURRENT hashes per process, others wait briefly then get 503."""

import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import get_settings
from app.core.db import engine
from app.models import User
from tests.conftest import PASSWORD, FakeMailer, new_client
from tests.test_invites import invite_event  # noqa: F401  (fixture re-export)


class SpyHasher:
    """Wraps the argon2 hasher: records pooled connections held and concurrency."""

    def __init__(self, real: Any, delay: float = 0.0) -> None:
        self.real, self.delay = real, delay
        self.connections: list[int] = []
        self.active = self.peak = 0
        self._lock = Lock()
        self.baseline = engine.pool.checkedout()

    def _wrap(self, fn: Callable[..., Any], *args: Any) -> Any:
        self.connections.append(engine.pool.checkedout() - self.baseline)
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            return fn(*args)
        finally:
            with self._lock:
                self.active -= 1

    def hash(self, *a: Any) -> Any:
        return self._wrap(self.real.hash, *a)

    def verify(self, *a: Any) -> Any:
        return self._wrap(self.real.verify, *a)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[SpyHasher]:
    s = SpyHasher(security._hasher)
    monkeypatch.setattr(security, "_hasher", s)
    security.reset_hash_slots()
    yield s
    security.reset_hash_slots()


def _login(c: TestClient, email: str, password: str = PASSWORD) -> int:
    return c.post("/api/auth/login", json={"email": email, "password": password}).status_code


def test_login_hashes_without_holding_a_db_connection(make_user: Callable[..., User], spy: SpyHasher) -> None:
    make_user("hash-me@example.com")
    spy.connections.clear()
    assert _login(new_client(), "hash-me@example.com") == 200
    assert _login(new_client(), "hash-me@example.com", "wrong-password-1") == 401
    assert _login(new_client(), "nobody-here@example.com") == 401  # dummy hash path too
    assert spy.connections and set(spy.connections) == {0}, spy.connections


def test_signup_and_reset_hash_without_holding_a_db_connection(spy: SpyHasher, mailer: FakeMailer) -> None:
    c = new_client()
    assert c.post("/api/auth/signup", json={"email": "new-hash@example.com", "password": PASSWORD}).status_code == 202
    c.post("/api/auth/forgot-password", json={"email": "new-hash@example.com"})
    token = mailer.last_link_token("new-hash@example.com")
    assert c.post("/api/auth/reset-password", json={"token": token, "password": "another-pass-12"}).status_code == 200
    assert spy.connections and set(spy.connections) == {0}, spy.connections


def test_delete_me_and_invite_register_hash_without_holding_a_db_connection(
    make_user: Callable[..., User], login_as: Callable[..., TestClient], invite_event, mailer: FakeMailer, spy: SpyHasher  # noqa: F811
) -> None:
    u = make_user("leaver-hash@example.com")
    c = login_as(u)
    spy.connections.clear()
    assert c.request("DELETE", "/api/me", json={"password": "wrong-password-9"}).status_code == 403
    event, org = invite_event
    org.post(f"/api/events/{event.id}/invites", json={"csv": "invitee-hash@example.com"})
    token = next(m for m in reversed(mailer.outbox) if m.to == "invitee-hash@example.com").body.split("/invite/")[1].split()[0]
    assert new_client().post("/api/invites/register", json={"token": token, "password": PASSWORD}).status_code == 201
    assert spy.connections and set(spy.connections) == {0}, spy.connections


def test_concurrent_hashing_is_capped_and_excess_gets_busy(make_user: Callable[..., User], monkeypatch: pytest.MonkeyPatch) -> None:
    make_user("burst@example.com")
    monkeypatch.setattr(get_settings(), "password_hash_max_concurrent", 2)
    monkeypatch.setattr(get_settings(), "password_hash_wait_seconds", 0.3)
    slow = SpyHasher(security._hasher, delay=1.0)
    monkeypatch.setattr(security, "_hasher", slow)
    security.reset_hash_slots()
    clients = [new_client() for _ in range(6)]
    barrier = Barrier(len(clients))

    def go(c: TestClient) -> tuple[int, str | None]:
        barrier.wait()
        r = c.post("/api/auth/login", json={"email": "burst@example.com", "password": "wrong-password-1"})
        return r.status_code, r.headers.get("retry-after")

    try:
        with ThreadPoolExecutor(len(clients)) as pool:
            results = list(pool.map(go, clients))
    finally:
        security.reset_hash_slots()
    codes = [code for code, _ in results]
    assert slow.peak <= 2, slow.peak
    assert codes.count(401) >= 2 and codes.count(503) >= 1, codes
    assert all(code in (401, 503) for code in codes), codes
    assert all(ra for code, ra in results if code == 503)
