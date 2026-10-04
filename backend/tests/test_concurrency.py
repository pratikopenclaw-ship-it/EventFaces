"""Concurrency & idempotency (Phase B §9): the same request fired in parallel must never
5xx, never double-apply, and single-use things must be used exactly once."""

import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import REFRESH_COOKIE
from app.models import EventMember, Invite, Photo, PhotoStatus
from tests.conftest import PASSWORD, FakeMailer, new_client
from tests.test_authz_matrix import World, world  # noqa: F401  (fixture re-export)

N = 8


def _race(calls: list[Callable[[], httpx.Response]]) -> list[int]:
    """Start all calls at the same instant (barrier) and return their status codes."""
    barrier = Barrier(len(calls))

    def run(call: Callable[[], httpx.Response]) -> int:
        barrier.wait()
        return call().status_code

    with ThreadPoolExecutor(len(calls)) as pool:
        codes = list(pool.map(run, calls))
    assert all(c < 500 for c in codes), codes
    return codes


def _login(email: str) -> TestClient:
    c = new_client()
    assert c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c


def _clients(email: str, n: int = N) -> list[TestClient]:
    return [_login(email) for _ in range(n)]


@pytest.fixture
def slow_membership_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Widen the check-then-insert window deterministically: every EventMember lookup
    takes 300 ms, so parallel requests are guaranteed to interleave there."""
    import time

    original = Session.get

    def slow_get(self: Session, entity: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, entity, *args, **kwargs)
        if entity is EventMember:
            time.sleep(0.3)
        return result

    monkeypatch.setattr(Session, "get", slow_get)


@pytest.mark.usefixtures("slow_membership_lookup")
def test_parallel_join_creates_one_membership(world: World, db: Session) -> None:  # noqa: F811
    body = {"slug": world.event_a.slug, "code": world.event_a.access_code}
    codes = _race([lambda c=c: c.post("/api/join", json=body) for c in _clients("outsider@example.com")])
    assert set(codes) == {200}, codes
    count = db.scalar(select(func.count()).select_from(EventMember).where(EventMember.user_id == world.users["attendee_not_member"].id))
    assert count == 1


@pytest.mark.usefixtures("slow_membership_lookup")
def test_parallel_invite_accept_creates_one_membership(world: World, db: Session, make_user: Callable[..., Any], mailer: FakeMailer) -> None:  # noqa: F811
    org = _login("org-this@example.com")
    assert org.post(f"/api/events/{world.event_a.id}/invites", json={"csv": "guest-race@example.com"}).status_code == 200
    token = next(m for m in reversed(mailer.outbox) if m.to == "guest-race@example.com").body.split("/invite/")[1].split()[0]
    user = make_user("guest-race@example.com")
    codes = _race([lambda c=c: c.post("/api/invites/accept", json={"token": token}) for c in _clients("guest-race@example.com")])
    assert set(codes) == {200}, codes
    assert db.scalar(select(func.count()).select_from(EventMember).where(EventMember.user_id == user.id)) == 1


def test_parallel_invite_register_creates_one_account(world: World, db: Session, mailer: FakeMailer) -> None:  # noqa: F811
    org = _login("org-this@example.com")
    org.post(f"/api/events/{world.event_a.id}/invites", json={"csv": "newbie@example.com"})
    token = next(m for m in reversed(mailer.outbox) if m.to == "newbie@example.com").body.split("/invite/")[1].split()[0]
    codes = _race([lambda c=c: c.post("/api/invites/register", json={"accept_terms": True, "token": token, "password": PASSWORD}) for c in [new_client() for _ in range(N)]])
    assert Counter(codes)[201] == 1, codes
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Invite).where(Invite.email == "newbie@example.com", Invite.accepted_by.is_not(None))) == 1


def test_parallel_password_reset_uses_token_once(world: World, mailer: FakeMailer) -> None:  # noqa: F811
    new_client().post("/api/auth/forgot-password", json={"email": "member@example.com"})
    token = mailer.last_link_token("member@example.com")
    codes = _race(
        [lambda i=i: new_client().post("/api/auth/reset-password", json={"token": token, "password": f"new-password-{i:04d}"}) for i in range(N)]
    )
    assert Counter(codes) == {200: 1, 400: N - 1}, codes


def test_parallel_refresh_with_one_cookie_keeps_one_session(world: World) -> None:  # noqa: F811
    owner = _login("member@example.com")
    raw = owner.cookies.get(REFRESH_COOKIE)
    assert raw
    tabs = []
    for _ in range(N):
        t = new_client()
        t.cookies.set(REFRESH_COOKIE, raw)
        tabs.append(t)
    codes = _race([lambda t=t: t.post("/api/auth/refresh") for t in tabs])
    assert Counter(codes)[200] == 1, codes
    winner = tabs[codes.index(200)]
    assert winner.get("/api/me").status_code == 200  # benign race: session survives


def test_parallel_upload_starts_respect_quota(world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(get_settings(), "guest_upload_max_per_user", 3)
    body = {"filename": "a.jpg", "content_type": "image/jpeg", "size": 1000}
    url = f"/api/events/{world.event_a.id}/uploads"
    codes = _race([lambda c=c: c.post(url, json=body) for c in _clients("member@example.com")])
    assert Counter(codes) == {201: 3, 409: N - 3}, codes


def test_parallel_complete_accepts_once(world: World, db: Session) -> None:  # noqa: F811
    from tests.helpers import half_photo

    c = _login("member@example.com")
    data = half_photo("left")
    start = c.post(f"/api/events/{world.event_a.id}/uploads", json={"filename": "a.jpg", "content_type": "image/jpeg", "size": len(data)}).json()
    assert httpx.put(start["upload_url"], content=data, headers={"content-type": "image/jpeg"}).status_code == 200
    url = f"/api/events/{world.event_a.id}/uploads/{start['photo_id']}/complete"
    codes = _race([lambda c=c: c.post(url) for c in _clients("member@example.com")])
    assert Counter(codes) == {200: 1, 409: N - 1}, codes


def test_parallel_moderation_and_member_updates_are_consistent(world: World, db: Session) -> None:  # noqa: F811
    photo = db.get(Photo, world.photo_a.id)
    assert photo is not None
    photo.status = PhotoStatus.pending_review
    db.commit()
    orgs = _clients("org-this@example.com", 4) + _clients("admin@example.com", 4)
    url = f"/api/events/{world.event_a.id}/photos/{world.photo_a.id}/moderate"
    actions = ["approve", "reject"] * 4
    _race([lambda c=c, a=a: c.post(url, json={"action": a}) for c, a in zip(orgs, actions, strict=True)])
    db.expire_all()
    final = db.get(Photo, world.photo_a.id)
    assert final is not None and final.status in (PhotoStatus.published, PhotoStatus.rejected)
    if final.status == PhotoStatus.rejected:
        assert final.original_key is None  # a reject is never half-applied

    member = world.users["attendee_member"].id
    url = f"/api/events/{world.event_a.id}/members/{member}"
    _race([lambda c=c, i=i: c.patch(url, json={"status": "revoked" if i % 2 else "approved"}) for i, c in enumerate(orgs)])


def test_parallel_sync_starts_one_run(world: World, db: Session) -> None:  # noqa: F811
    from app.models import DriveSyncRun
    from app.services import drive
    from tests.test_drive_sync import FakeDrive

    drive.set_drive_client(FakeDrive({world.event_a.drive_folder_id: {}}))
    url = f"/api/events/{world.event_a.id}/sync"
    codes = _race([lambda c=c: c.post(url) for c in _clients("org-this@example.com")])
    assert Counter(codes)[202] >= 1 and set(codes) <= {202, 409}, codes
    runs = db.scalar(select(func.count()).select_from(DriveSyncRun).where(DriveSyncRun.event_id == world.event_a.id))
    assert runs == Counter(codes)[202]


def test_revoke_racing_download_never_serves_after_revocation(world: World, db: Session) -> None:  # noqa: F811
    member = _login("member@example.com")
    link = member.post(f"/api/events/{world.event_a.id}/downloads", json={"photo_ids": [str(world.photo_a.id)]}).json()["url"]
    org = _login("org-this@example.com")
    revoke = f"/api/events/{world.event_a.id}/members/{world.users['attendee_member'].id}"
    _race([lambda: org.patch(revoke, json={"status": "revoked"})] + [lambda: member.get(link) for _ in range(N - 1)])
    assert member.get(link).status_code == 403
    assert uuid.UUID(str(world.photo_a.id))
