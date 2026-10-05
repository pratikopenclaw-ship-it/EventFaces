"""Event isolation: only approved, non-expired members reach event-scoped endpoints."""

from datetime import timedelta

import pytest

from app.core.security import utcnow
from app.models import JoinMode, MemberRole, MemberStatus, UserRole


def test_non_member_gets_403(make_user, login_as, make_event) -> None:
    event = make_event()
    outsider = login_as(make_user("out@example.com"))
    assert outsider.get(f"/api/events/{event.id}").status_code == 403
    assert outsider.get("/api/events").json() == []


def test_unknown_event_id_is_403_not_404(make_user, login_as) -> None:
    c = login_as(make_user("out@example.com"))
    assert c.get("/api/events/00000000-0000-0000-0000-000000000000").status_code == 403


@pytest.mark.parametrize(
    ("status", "expires_in"),
    [
        (MemberStatus.pending, None),
        (MemberStatus.revoked, None),
        (MemberStatus.approved, timedelta(seconds=-1)),
    ],
)
def test_inactive_membership_gets_403(make_user, login_as, make_event, add_member, status, expires_in) -> None:
    user = make_user("m@example.com")
    event = make_event()
    add_member(event, user, status=status, expires_in=expires_in)
    c = login_as(user)
    assert c.get(f"/api/events/{event.id}").status_code == 403
    assert c.get("/api/events").json() == []


def test_event_access_window_expired(make_user, login_as, make_event, add_member) -> None:
    att_user = make_user("att@example.com")
    org_user = make_user("org@example.com", UserRole.organizer)
    event = make_event(access_expires_at=utcnow() - timedelta(minutes=1))
    add_member(event, att_user)
    add_member(event, org_user, role=MemberRole.organizer)

    assert login_as(att_user).get(f"/api/events/{event.id}").status_code == 403
    # organizers keep management access after the attendee window closes
    assert login_as(org_user).get(f"/api/events/{event.id}/admin").status_code == 200


def test_unverified_user_cannot_access_events(make_user, login_as, make_event, add_member) -> None:
    user = make_user("unverified@example.com", verified=False)
    event = make_event()
    add_member(event, user)
    c = login_as(user)
    assert c.get(f"/api/events/{event.id}").status_code == 403
    assert c.post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 403


def test_join_preview_shows_only_what_the_join_page_needs(make_user, login_as, make_event) -> None:
    """Before joining: name, date, how to join and the colour (for the event's cover). Never
    the code, the logo (that needs membership) or anything else."""
    event = make_event(accent_color="#7c3aed", description="Members only")
    preview = login_as(make_user("peek@example.com")).get(f"/api/join/{event.slug}").json()
    assert set(preview) == {"slug", "name", "date", "join_mode", "accent_color"}
    assert preview["accent_color"] == "#7c3aed"


def test_join_by_code(make_user, login_as, make_event) -> None:
    event = make_event()
    c = login_as(make_user("att@example.com"))
    assert c.get(f"/api/events/{event.id}").status_code == 403

    preview = c.get(f"/api/join/{event.slug}").json()
    assert preview["name"] == event.name and "access_code" not in preview

    # codes are case/whitespace-insensitive
    code = f" {event.access_code[:4].lower()}-{event.access_code[4:]} "
    r = c.post("/api/join", json={"slug": event.slug, "code": code})
    assert r.status_code == 200, r.text
    assert c.get(f"/api/events/{event.id}").status_code == 200
    # idempotent
    assert c.post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 200


def test_code_for_one_event_does_not_open_another(make_user, login_as, make_event) -> None:
    a, b = make_event("A"), make_event("B")
    c = login_as(make_user("att@example.com"))
    assert c.post("/api/join", json={"slug": b.slug, "code": a.access_code}).status_code == 400
    assert c.get(f"/api/events/{b.id}").status_code == 403


def test_join_rejected_for_invite_only_event(make_user, login_as, make_event) -> None:
    event = make_event(join_mode=JoinMode.invite)
    c = login_as(make_user("att@example.com"))
    r = c.post("/api/join", json={"slug": event.slug, "code": event.access_code})
    assert r.status_code == 403
    assert c.get(f"/api/events/{event.id}").status_code == 403


def test_join_rejected_after_access_expired(make_user, login_as, make_event) -> None:
    event = make_event(access_expires_at=utcnow() - timedelta(seconds=1))
    c = login_as(make_user("att@example.com"))
    assert c.post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 403


def test_revoked_member_cannot_rejoin_with_code(make_user, login_as, make_event, add_member) -> None:
    user = make_user("att@example.com")
    event = make_event()
    add_member(event, user, status=MemberStatus.revoked)
    c = login_as(user)
    assert c.post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 403


def test_wrong_codes_lock_out(make_user, login_as, make_event) -> None:
    event = make_event()
    c = login_as(make_user("att@example.com"))
    for _ in range(5):
        assert c.post("/api/join", json={"slug": event.slug, "code": "WRONGCODE"}).status_code == 400
    # locked: even the correct code is refused now
    assert c.post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 429
    assert c.get(f"/api/events/{event.id}").status_code == 403


def test_lockout_also_applies_per_ip_across_accounts(make_user, login_as, make_event) -> None:
    event = make_event()
    first = login_as(make_user("one@example.com"))
    for _ in range(5):
        first.post("/api/join", json={"slug": event.slug, "code": "WRONGCODE"})
    second = login_as(make_user("two@example.com"))  # same test client IP
    assert second.post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 429


def test_organizer_revokes_attendee(make_user, login_as, make_event, add_member) -> None:
    org_user = make_user("org@example.com", UserRole.organizer)
    att_user = make_user("att@example.com")
    event = make_event()
    add_member(event, org_user, role=MemberRole.organizer)
    add_member(event, att_user)
    att = login_as(att_user)
    assert att.get(f"/api/events/{event.id}").status_code == 200

    r = login_as(org_user).patch(f"/api/events/{event.id}/members/{att_user.id}", json={"status": "revoked"})
    assert r.status_code == 200
    assert att.get(f"/api/events/{event.id}").status_code == 403


def test_rotated_code_invalidates_old_code(make_user, login_as, make_event) -> None:
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    event = make_event()
    old = event.access_code
    new = admin.post(f"/api/events/{event.id}/access-code/rotate").json()["access_code"]
    assert new != old
    c = login_as(make_user("att@example.com"))
    assert c.post("/api/join", json={"slug": event.slug, "code": old}).status_code == 400
    assert c.post("/api/join", json={"slug": event.slug, "code": new}).status_code == 200
