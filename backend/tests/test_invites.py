"""Invite-only events: CSV invites, magic links, account creation from a link, QR codes."""

from datetime import timedelta

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import ACCESS_COOKIE, utcnow
from app.models import Invite, JoinMode, MemberRole, MemberStatus, UserRole
from app.services.invites import parse_emails
from tests.conftest import PASSWORD, new_client


def test_parse_emails_handles_messy_csv() -> None:
    text = 'Name,Email\nAnna,Anna@Example.com\n"Bob";bob@example.com\nanna@example.com\nnot-an-email@\nfoo bar,\n'
    parsed = parse_emails(text)
    assert parsed.valid == ["anna@example.com", "bob@example.com"]
    assert parsed.invalid == ["not-an-email@"]


@pytest.fixture
def invite_event(make_user, login_as, make_event, add_member):
    org_user = make_user("org@example.com", UserRole.organizer)
    event = make_event("Private Gala", join_mode=JoinMode.invite)
    add_member(event, org_user, role=MemberRole.organizer)
    return event, login_as(org_user)


def _invite(org, event, mailer, csv: str) -> dict:
    r = org.post(f"/api/events/{event.id}/invites", json={"csv": csv})
    assert r.status_code == 200, r.text
    return r.json()


def _link_token(mailer, email: str) -> str:
    mail = next(m for m in reversed(mailer.outbox) if m.to == email)
    return mail.body.split("/invite/")[1].split()[0]


def test_invite_upload_and_accept_logged_in(invite_event, make_user, login_as, mailer, db) -> None:
    event, org = invite_event
    guest = make_user("guest@example.com")
    result = _invite(org, event, mailer, "email\nguest@example.com\nnew@example.com\nbad@\n")
    assert sorted(result["sent"]) == ["guest@example.com", "new@example.com"]
    assert result["invalid"] == ["bad@"]
    assert "Private Gala" in mailer.outbox[-1].subject

    c = login_as(guest)
    assert c.get(f"/api/events/{event.id}").status_code == 403
    token = _link_token(mailer, "guest@example.com")
    preview = new_client().get(f"/api/invites/{token}").json()
    assert preview == {"event_name": "Private Gala", "event_date": None, "email": "guest@example.com", "account_exists": True, "accepted": False}

    assert c.post("/api/invites/accept", json={"token": token}).status_code == 200
    assert c.get(f"/api/events/{event.id}").status_code == 200
    assert c.post("/api/invites/accept", json={"token": token}).status_code == 200  # idempotent for the same user
    assert db.scalar(select(Invite.status).where(Invite.email == "guest@example.com")).value == "accepted"

    # Re-uploading the same list skips people who already joined
    again = _invite(org, event, mailer, "guest@example.com")
    assert again["sent"] == [] and again["already_members"] == ["guest@example.com"]


def test_invite_is_bound_to_the_invited_email(invite_event, make_user, login_as, mailer, db) -> None:
    event, org = invite_event
    _invite(org, event, mailer, "guest@example.com")
    token = _link_token(mailer, "guest@example.com")
    thief = login_as(make_user("forwarded-to@example.com"))
    r = thief.post("/api/invites/accept", json={"token": token})
    assert r.status_code == 403 and "guest@example.com" in r.json()["detail"]
    assert thief.get(f"/api/events/{event.id}").status_code == 403


def test_register_from_invite_creates_verified_member_and_logs_in(invite_event, mailer, db) -> None:
    event, org = invite_event
    _invite(org, event, mailer, "newbie@example.com")
    token = _link_token(mailer, "newbie@example.com")

    c = new_client()
    assert c.get(f"/api/invites/{token}").json()["account_exists"] is False
    r = c.post("/api/invites/register", json={"accept_terms": True, "token": token, "password": PASSWORD})
    assert r.status_code == 201, r.text
    assert r.json()["email_verified_at"] is not None
    assert c.cookies.get(ACCESS_COOKIE)
    assert c.get(f"/api/events/{event.id}").status_code == 200

    # The link can't be used to create a second account or be re-registered
    assert new_client().post("/api/invites/register", json={"accept_terms": True, "token": token, "password": PASSWORD}).status_code == 409


def test_register_refused_when_account_exists(invite_event, make_user, mailer) -> None:
    event, org = invite_event
    make_user("existing@example.com")
    _invite(org, event, mailer, "existing@example.com")
    token = _link_token(mailer, "existing@example.com")
    assert new_client().post("/api/invites/register", json={"accept_terms": True, "token": token, "password": PASSWORD}).status_code == 409


def test_revoked_expired_and_rotated_links(invite_event, make_user, login_as, mailer, db) -> None:
    event, org = invite_event
    guest = login_as(make_user("guest@example.com"))
    _invite(org, event, mailer, "guest@example.com")
    first = _link_token(mailer, "guest@example.com")
    invite_id = org.get(f"/api/events/{event.id}/invites").json()[0]["id"]

    # Resend rotates the token: the old link dies, the new one works
    assert org.post(f"/api/events/{event.id}/invites/{invite_id}/resend").status_code == 200
    second = _link_token(mailer, "guest@example.com")
    assert first != second
    assert guest.post("/api/invites/accept", json={"token": first}).status_code == 410

    # Revoked
    assert org.delete(f"/api/events/{event.id}/invites/{invite_id}").json()["status"] == "revoked"
    assert guest.post("/api/invites/accept", json={"token": second}).status_code == 410

    # Expired
    _invite(org, event, mailer, "guest@example.com")
    third = _link_token(mailer, "guest@example.com")
    db.scalar(select(Invite)).expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert guest.post("/api/invites/accept", json={"token": third}).status_code == 410
    assert guest.get(f"/api/events/{event.id}").status_code == 403


def test_invite_does_not_undo_revocation(invite_event, make_user, login_as, add_member, mailer) -> None:
    event, org = invite_event
    user = make_user("guest@example.com")
    _invite(org, event, mailer, "guest@example.com")
    add_member(event, user, status=MemberStatus.revoked)  # revoked after being invited
    c = login_as(user)
    assert c.post("/api/invites/accept", json={"token": _link_token(mailer, "guest@example.com")}).status_code == 403
    assert c.get(f"/api/events/{event.id}").status_code == 403


def test_invite_only_event_rejects_code_join(invite_event, make_user, login_as) -> None:
    event, _ = invite_event
    c = login_as(make_user("x@example.com"))
    assert c.post("/api/join", json={"slug": event.slug, "code": event.access_code}).status_code == 403


def test_only_organizers_manage_invites(invite_event, make_user, login_as, add_member) -> None:
    event, _ = invite_event
    attendee = make_user("att@example.com")
    add_member(event, attendee)
    c = login_as(attendee)
    assert c.post(f"/api/events/{event.id}/invites", json={"csv": "a@example.com"}).status_code == 403
    assert c.get(f"/api/events/{event.id}/invites").status_code == 403


def test_qr_code_encodes_join_link(make_user, login_as, make_event, add_member) -> None:
    org_user = make_user("org@example.com", UserRole.organizer)
    event = make_event("Open Party")
    add_member(event, org_user, role=MemberRole.organizer)
    org = login_as(org_user)

    svg = org.get(f"/api/events/{event.id}/qr")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    png = org.get(f"/api/events/{event.id}/qr?format=png")
    assert png.headers["content-type"] == "image/png"

    img = cv2.imdecode(np.frombuffer(png.content, np.uint8), cv2.IMREAD_COLOR)
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert decoded == f"{get_settings().frontend_url}/join/{event.slug}?code={event.access_code}"

    attendee = make_user("att@example.com")
    add_member(event, attendee)
    assert login_as(attendee).get(f"/api/events/{event.id}/qr").status_code == 403

    invite_only = make_event("Closed", join_mode=JoinMode.invite)
    add_member(invite_only, org_user, role=MemberRole.organizer)
    assert org.get(f"/api/events/{invite_only.id}/qr").status_code == 400
