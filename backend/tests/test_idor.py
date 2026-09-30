"""IDOR / event isolation: an actor who is legitimately authorized on event A passes an
object ID that belongs to event B through event A's routes. Every such request must fail
exactly like a request for an ID that does not exist (same status, same body, so the
response does not reveal that the object exists elsewhere), and must have no side effect."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.security import hash_token, utcnow
from app.models import (
    EventMember,
    IndexStatus,
    Invite,
    MemberRole,
    MemberStatus,
    Photo,
    PhotoReport,
    PhotoSource,
    PhotoStatus,
    RemovalRequest,
    RemovalStatus,
    SearchGrant,
    User,
)
from tests.conftest import PASSWORD, new_client
from tests.helpers import solid_jpeg
from tests.test_authz_matrix import _PW_HASH, World, world  # noqa: F401  (fixture re-export)


def _photo(db: Session, event_id: uuid.UUID, **kw: Any) -> Photo:
    p = Photo(
        id=uuid.uuid4(),
        event_id=event_id,
        source=kw.pop("source", PhotoSource.drive),
        drive_file_id=f"f-{uuid.uuid4().hex[:8]}",
        original_filename="p.jpg",
        status=kw.pop("status", PhotoStatus.published),
        index_status=IndexStatus.indexed,
        **kw,
    )
    for variant in ("original", "preview", "thumb"):
        key = storage.photo_key(event_id, p.id, variant)
        storage.put_jpeg(key, solid_jpeg())
        setattr(p, f"{variant}_key", key)
    db.add(p)
    return p


@pytest.fixture
def b_objects(db: Session, world: World) -> dict[str, str]:  # noqa: F811
    now = utcnow()
    b = world.event_b
    b_user = User(email="b-attendee@example.com", password_hash=_PW_HASH, email_verified_at=now)
    db.add(b_user)
    db.flush()
    db.add(EventMember(event_id=b.id, user_id=b_user.id, role=MemberRole.attendee, status=MemberStatus.approved))
    photo = _photo(db, b.id)
    # A guest upload in B by A's member (e.g. a stale ID they remember): still not finalizable via A.
    pending = _photo(db, b.id, source=PhotoSource.guest, status=PhotoStatus.processing, uploaded_by=world.users["attendee_member"].id)
    invite = Invite(event_id=b.id, email="b-invitee@example.com", token_hash=hash_token(uuid.uuid4().hex), expires_at=now + timedelta(days=5))
    db.add(invite)
    db.flush()
    report = PhotoReport(photo_id=photo.id, event_id=b.id, reporter_id=b_user.id, reason="other")
    removal = RemovalRequest(event_id=b.id, email="b@example.com", token_hash=hash_token(uuid.uuid4().hex), status=RemovalStatus.submitted, matched_photo_ids=[photo.id])
    # A's member even holds a (stale) grant on B's photo: it must not be usable through A.
    grant = SearchGrant(user_id=world.users["attendee_member"].id, photo_id=photo.id, event_id=b.id, similarity=0.9, expires_at=now + timedelta(days=1))
    db.add_all([report, removal, grant])
    db.commit()
    return {
        "photo": str(photo.id),
        "pending": str(pending.id),
        "invite": str(invite.id),
        "report": str(report.id),
        "removal": str(removal.id),
        "member": str(b_user.id),
    }


def _login(email: str) -> TestClient:
    c = new_client()
    assert c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c


# (actor on A, method, path under /api/events/{A}, object kind, body)
CASES: list[tuple[str, str, str, str, Any]] = [
    ("member", "GET", "/photos/{id}/thumb", "photo", None),
    ("member", "GET", "/photos/{id}/preview", "photo", None),
    ("member", "POST", "/photos/{id}/report", "photo", {"reason": "other"}),
    ("member", "POST", "/uploads/{id}/complete", "pending", None),
    ("organizer", "GET", "/photos/{id}/preview", "photo", None),
    ("organizer", "DELETE", "/photos/{id}", "photo", None),
    ("organizer", "POST", "/photos/{id}/moderate", "photo", {"action": "reject"}),
    ("organizer", "PATCH", "/members/{id}", "member", {"expires_at": None}),
    ("organizer", "DELETE", "/members/{id}", "member", None),
    ("organizer", "POST", "/invites/{id}/resend", "invite", None),
    ("organizer", "DELETE", "/invites/{id}", "invite", None),
    ("organizer", "POST", "/reports/{id}/resolve", "report", {"action": "remove_photo"}),
    ("organizer", "POST", "/removal-requests/{id}/resolve", "removal", {"action": "remove", "photo_ids": []}),
    ("admin", "DELETE", "/photos/{id}", "photo", None),
    ("admin", "DELETE", "/members/{id}", "member", None),
    ("admin", "POST", "/reports/{id}/resolve", "report", {"action": "remove_photo"}),
]
ACTORS = {"member": "member@example.com", "organizer": "org-this@example.com", "admin": "admin@example.com"}


def _snapshot(db: Session, world: World) -> tuple[Any, ...]:  # noqa: F811 - `world` is the fixture value
    """Everything a cross-event request could have changed in event B."""
    db.expire_all()
    b = world.event_b.id
    return (
        sorted((str(p.id), p.status.value) for p in db.scalars(select(Photo).where(Photo.event_id == b))),
        sorted((str(m.user_id), m.status.value, m.expires_at) for m in db.scalars(select(EventMember).where(EventMember.event_id == b))),
        sorted((str(i.id), i.status.value, i.sent_at, i.token_hash) for i in db.scalars(select(Invite).where(Invite.event_id == b))),
        sorted((str(r.id), r.status.value) for r in db.scalars(select(PhotoReport).where(PhotoReport.event_id == b))),
        sorted((str(r.id), r.status.value) for r in db.scalars(select(RemovalRequest).where(RemovalRequest.event_id == b))),
    )


@pytest.mark.parametrize(("actor", "method", "path", "kind", "body"), CASES, ids=[f"{a}-{m} {p}" for a, m, p, _, _ in CASES])
def test_foreign_event_ids_are_indistinguishable_from_missing(
    actor: str, method: str, path: str, kind: str, body: Any, world: World, b_objects: dict[str, str], db: Session  # noqa: F811
) -> None:
    c = _login(ACTORS[actor])
    base = f"/api/events/{world.event_a.id}"
    before = _snapshot(db, world)

    foreign = c.request(method, base + path.format(id=b_objects[kind]), json=body)
    missing = c.request(method, base + path.format(id=uuid.uuid4()), json=body)

    assert foreign.status_code == 404, f"{foreign.status_code} {foreign.text}"
    assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json())
    assert _snapshot(db, world) == before, "cross-event request changed event B"


def test_download_of_foreign_event_photo_is_refused(world: World, b_objects: dict[str, str]) -> None:  # noqa: F811
    c = _login("member@example.com")
    r = c.post(f"/api/events/{world.event_a.id}/downloads", json={"photo_ids": [b_objects["photo"]]})
    assert r.status_code in (403, 404), r.text
    assert "token" not in r.text


def test_feedback_on_foreign_event_photo_is_refused(world: World, b_objects: dict[str, str]) -> None:  # noqa: F811
    c = _login("member@example.com")
    r = c.post(f"/api/events/{world.event_a.id}/feedback", json={"photo_id": b_objects["photo"], "verdict": "me"})
    assert r.status_code in (403, 404), r.text


def test_download_token_is_bound_to_its_user(world: World) -> None:  # noqa: F811
    owner = _login("member@example.com")
    r = owner.post(f"/api/events/{world.event_a.id}/downloads", json={"photo_ids": [str(world.photo_a.id)]})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    for other in ("org-this@example.com", "admin@example.com", "outsider@example.com"):
        assert _login(other).get(url).status_code in (403, 404), other
    assert new_client().get(url).status_code == 401
    assert owner.get(url).status_code == 200


def test_listings_never_include_other_events(world: World, b_objects: dict[str, str]) -> None:  # noqa: F811
    """Pagination/sorting/filter parameters cannot widen a listing beyond event A."""
    c = _login("admin@example.com")
    base = f"/api/events/{world.event_a.id}"
    foreign = set(b_objects.values())
    for path in (
        "/photos?page=1&page_size=100",
        "/photos?status=published",
        "/photos?page=2",
        "/moderation",
        "/reports",
        "/removal-requests",
        "/members",
        "/invites",
        "/search-log",
        "/my-photos",
        "/my-uploads",
    ):
        r = c.get(base + path)
        assert r.status_code == 200, (path, r.status_code, r.text)
        leaked = [v for v in foreign if v in r.text]
        assert not leaked, (path, leaked)


def test_download_link_replay_is_rate_limited(world: World) -> None:  # noqa: F811
    """SEC-028: a ZIP link can't be replayed endlessly to multiply egress/CPU."""
    c = _login("member@example.com")
    r = c.post(f"/api/events/{world.event_a.id}/downloads", json={"photo_ids": [str(world.photo_a.id)]})
    url = r.json()["url"]
    codes = [c.get(url).status_code for _ in range(125)]
    assert codes[:120] == [200] * 120
    assert codes[-1] == 429
