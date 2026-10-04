"""Revoked/expired members lose access on their very next request (no cached authorization,
including outstanding signed download links), and request bodies cannot set fields the
schema doesn't expose (role, verification, ownership, access code...)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import legal
from app.core.security import utcnow
from app.models import Event, EventMember, MemberRole, MemberStatus, User, UserRole
from tests.conftest import PASSWORD, new_client
from tests.test_authz_matrix import World, world  # noqa: F401  (fixture re-export)


def _login(email: str) -> TestClient:
    c = new_client()
    assert c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c


def _member_urls(w: World) -> list[str]:
    e = w.event_a.id
    return [f"/api/events/{e}", f"/api/events/{e}/my-photos", f"/api/events/{e}/photos/{w.photo_a.id}/thumb"]


def _issue_download(c: TestClient, w: World) -> str:
    r = c.post(f"/api/events/{w.event_a.id}/downloads", json={"photo_ids": [str(w.photo_a.id)]})
    assert r.status_code == 200, r.text
    url: str = r.json()["url"]
    return url


def _set_membership(db: Session, w: World, **values: object) -> None:
    m = db.get(EventMember, (w.event_a.id, w.users["attendee_member"].id))
    assert m is not None
    for k, v in values.items():
        setattr(m, k, v)
    db.commit()


@pytest.mark.parametrize(
    "change",
    [
        {"status": MemberStatus.revoked},
        {"status": MemberStatus.pending},
        {"expires_at": "past"},
    ],
    ids=["revoked", "back-to-pending", "membership-expired"],
)
def test_losing_membership_takes_effect_immediately(change: dict[str, object], world: World, db: Session) -> None:  # noqa: F811
    c = _login("member@example.com")
    for url in _member_urls(world):
        assert c.get(url).status_code == 200, url
    link = _issue_download(c, world)

    if change.get("expires_at") == "past":
        change = {"expires_at": utcnow() - timedelta(seconds=1)}
    _set_membership(db, world, **change)

    # Same session, same (still unexpired) access JWT, same signed link.
    for url in _member_urls(world):
        assert c.get(url).status_code == 403, url
    assert c.get(link).status_code == 403
    assert c.post(f"/api/events/{world.event_a.id}/downloads", json={"photo_ids": [str(world.photo_a.id)]}).status_code == 403


def test_event_access_end_revokes_everyone_but_admins(world: World, db: Session) -> None:  # noqa: F811
    member = _login("member@example.com")
    link = _issue_download(member, world)
    world.event_a.access_expires_at = utcnow() - timedelta(seconds=1)
    db.merge(world.event_a)
    db.commit()
    assert member.get(f"/api/events/{world.event_a.id}").status_code == 403
    assert member.get(link).status_code == 403


def test_organizer_revoke_via_api_kills_outstanding_link(world: World) -> None:  # noqa: F811
    member, organizer = _login("member@example.com"), _login("org-this@example.com")
    link = _issue_download(member, world)
    r = organizer.patch(
        f"/api/events/{world.event_a.id}/members/{world.users['attendee_member'].id}", json={"status": "revoked"}
    )
    assert r.status_code == 200, r.text
    assert member.get(link).status_code == 403


def test_removed_photo_link_stops_working(world: World) -> None:  # noqa: F811
    member, organizer = _login("member@example.com"), _login("org-this@example.com")
    link = _issue_download(member, world)
    assert organizer.delete(f"/api/events/{world.event_a.id}/photos/{world.photo_a.id}").status_code in (200, 204)
    assert member.get(link).status_code == 403
    assert member.get(f"/api/events/{world.event_a.id}/photos/{world.photo_a.id}/thumb").status_code == 404


def test_account_deletion_ends_session_and_links(world: World) -> None:  # noqa: F811
    c = _login("member@example.com")
    link = _issue_download(c, world)
    assert c.request("DELETE", "/api/me", json={"password": PASSWORD}).status_code in (200, 204)
    assert c.get("/api/me").status_code == 401
    assert c.get(link).status_code == 401
    # The old refresh cookie cannot resurrect the session either.
    assert c.post("/api/auth/refresh").status_code == 401


def test_demoted_organizer_loses_admin_access_immediately(world: World, db: Session) -> None:  # noqa: F811
    c = _login("org-this@example.com")
    assert c.get(f"/api/events/{world.event_a.id}/members").status_code == 200
    m = db.get(EventMember, (world.event_a.id, world.users["organizer_this"].id))
    assert m is not None
    m.role = MemberRole.attendee
    db.commit()
    assert c.get(f"/api/events/{world.event_a.id}/members").status_code == 403


# --- mass assignment ---------------------------------------------------------------


def test_signup_ignores_privileged_fields(db: Session) -> None:
    c = new_client()
    r = c.post(
        "/api/auth/signup",
        json={
            "email": "sneaky@example.com",
            "password": PASSWORD,
            "accept_terms": True,
            "role": "super_admin",
            "terms_version": "1999-01-01",
            "organizer_terms_version": "2026-10-03",
            "email_verified_at": "2020-01-01T00:00:00Z",
            "is_verified": True,
            "face_consent_version": "x",
            "id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert r.status_code == 202, r.text
    u = db.scalar(select(User).where(User.email == "sneaky@example.com"))
    assert u is not None
    assert u.role == UserRole.attendee
    assert u.email_verified_at is None
    assert u.face_consent_version is None
    assert u.organizer_terms_version is None  # organizer terms are never accepted by sign-up
    assert u.terms_version == legal.VERSIONS["terms"]  # the server's version, not the client's
    assert str(u.id) != "00000000-0000-0000-0000-000000000001"


def test_event_patch_cannot_touch_server_owned_fields(world: World, db: Session) -> None:  # noqa: F811
    before = (world.event_a.slug, world.event_a.access_code, world.event_a.id, world.event_a.created_by)
    c = _login("org-this@example.com")
    r = c.patch(
        f"/api/events/{world.event_a.id}",
        json={
            "description": "ok",
            "slug": "hijacked",
            "access_code": "AAAAAAAA",
            "id": "00000000-0000-0000-0000-000000000001",
            "created_by": str(world.users["organizer_this"].id),
            "retention_completed_at": "2020-01-01T00:00:00Z",
        },
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    e = db.get(Event, world.event_a.id)
    assert e is not None
    assert (e.slug, e.access_code, e.id, e.created_by) == before
    assert e.retention_completed_at is None
    assert e.description == "ok"


def test_member_patch_cannot_change_role_or_user(world: World, db: Session) -> None:  # noqa: F811
    c = _login("org-this@example.com")
    target = world.users["attendee_member"].id
    r = c.patch(
        f"/api/events/{world.event_a.id}/members/{target}",
        json={"role": "organizer", "user_id": str(world.users["super_admin"].id), "event_id": str(world.event_b.id)},
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    m = db.get(EventMember, (world.event_a.id, target))
    assert m is not None and m.role == MemberRole.attendee


def test_organizer_cannot_revoke_a_fellow_organizer(world: World, db: Session) -> None:  # noqa: F811
    db.add(EventMember(event_id=world.event_a.id, user_id=world.users["organizer_other"].id, role=MemberRole.organizer, status=MemberStatus.approved))
    db.commit()
    c = _login("org-this@example.com")
    target = world.users["organizer_other"].id
    assert c.patch(f"/api/events/{world.event_a.id}/members/{target}", json={"status": "revoked"}).status_code == 403
    assert c.delete(f"/api/events/{world.event_a.id}/members/{target}").status_code == 403


def test_join_body_cannot_choose_role(world: World, db: Session) -> None:  # noqa: F811
    c = _login("outsider@example.com")
    r = c.post("/api/join", json={"slug": world.event_a.slug, "code": world.event_a.access_code, "role": "organizer", "status": "approved"})
    assert r.status_code in (200, 201), r.text
    m = db.get(EventMember, (world.event_a.id, world.users["attendee_not_member"].id))
    assert m is not None and m.role == MemberRole.attendee
    assert c.get(f"/api/events/{world.event_a.id}/members").status_code == 403
