"""Invite-only events: CSV of emails → one magic link per invitee.

The link token proves control of the invited inbox. Accepting requires the logged-in
account's email to equal the invited email; invitees without an account can create one
straight from the link (the token doubles as email verification).
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_token, new_opaque_token, utcnow
from app.models import Event, EventMember, Invite, InviteStatus, MemberRole, MemberStatus, User

MAX_INVITES_PER_UPLOAD = 2000


@dataclass
class ParsedEmails:
    valid: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)


def parse_emails(text: str) -> ParsedEmails:
    """Accept a CSV (any column containing '@'; a header row is ignored) or one email per line."""
    result = ParsedEmails()
    seen: set[str] = set()
    for row in csv.reader(io.StringIO(text.replace(";", ","))):
        for cell in row:
            value = cell.strip().strip('"').strip()
            if not value or value.lower() in {"email", "e-mail", "email address", "name"}:
                continue
            if "@" not in value:
                continue
            try:
                email = validate_email(value, check_deliverability=False).normalized.lower()
            except EmailNotValidError:
                result.invalid.append(value[:200])
                continue
            if email not in seen:
                seen.add(email)
                result.valid.append(email)
    return result


def invite_expiry(event: Event, now: datetime) -> datetime:
    expiry = now + timedelta(days=get_settings().invite_days)
    if event.access_expires_at is not None:
        expiry = min(expiry, event.access_expires_at)
    return expiry


@dataclass
class InviteOutcome:
    to_send: list[tuple[str, str]] = field(default_factory=list)  # (email, raw token)
    already_members: list[str] = field(default_factory=list)
    already_accepted: list[str] = field(default_factory=list)


def create_invites(db: Session, event: Event, inviter: User, emails: list[str]) -> InviteOutcome:
    if len(emails) > MAX_INVITES_PER_UPLOAD:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"At most {MAX_INVITES_PER_UPLOAD} invites at once")
    now = utcnow()
    out = InviteOutcome()
    existing = {i.email.lower(): i for i in db.scalars(select(Invite).where(Invite.event_id == event.id))}
    members = {
        email.lower()
        for email in db.scalars(
            select(User.email)
            .join(EventMember, EventMember.user_id == User.id)
            .where(EventMember.event_id == event.id, EventMember.status == MemberStatus.approved)
        )
    }
    for email in emails:
        if email in members:
            out.already_members.append(email)
            continue
        invite = existing.get(email)
        if invite is not None and invite.status == InviteStatus.accepted:
            out.already_accepted.append(email)
            continue
        raw = new_opaque_token()
        if invite is None:
            invite = Invite(event_id=event.id, email=email, invited_by=inviter.id)
            db.add(invite)
        invite.token_hash = hash_token(raw)  # re-inviting rotates the link
        invite.status = InviteStatus.pending
        invite.expires_at = invite_expiry(event, now)
        invite.sent_at = now
        out.to_send.append((email, raw))
    db.commit()
    return out


def rotate_token(db: Session, event: Event, invite: Invite) -> str:
    raw = new_opaque_token()
    invite.token_hash = hash_token(raw)
    invite.status = InviteStatus.pending
    invite.expires_at = invite_expiry(event, utcnow())
    invite.sent_at = utcnow()
    db.commit()
    return raw


def invite_link(raw_token: str) -> str:
    return f"{get_settings().frontend_url}/invite/{raw_token}"


def invite_email_body(event: Event, raw_token: str) -> str:
    when = f" on {event.date:%d %B %Y}" if event.date else ""
    return (
        f"You're invited to find your photos from {event.name}{when} on EventFaces.\n\n"
        f"Open your personal link (don't forward it, it's tied to this email address):\n\n"
        f"{invite_link(raw_token)}\n"
    )


def find_valid_invite(db: Session, raw_token: str) -> tuple[Invite, Event]:
    invite = db.scalar(select(Invite).where(Invite.token_hash == hash_token(raw_token)).with_for_update())
    now = utcnow()
    if invite is None or invite.status == InviteStatus.revoked or invite.expires_at <= now:
        raise HTTPException(status.HTTP_410_GONE, "This invite link is invalid or has expired")
    event = db.get(Event, invite.event_id)
    if event is None or (event.access_expires_at is not None and event.access_expires_at <= now):
        raise HTTPException(status.HTTP_410_GONE, "Access to this event has ended")
    return invite, event


def accept(db: Session, invite: Invite, event: Event, user: User) -> None:
    if user.email.lower() != invite.email.lower():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This invite is for {invite.email}. Log in with that address to accept it.",
        )
    if invite.status == InviteStatus.accepted and invite.accepted_by != user.id:
        raise HTTPException(status.HTTP_410_GONE, "This invite was already used")
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()  # the link was delivered to this inbox
    membership = db.get(EventMember, (event.id, user.id))
    if membership is None:
        db.add(EventMember(event_id=event.id, user_id=user.id, role=MemberRole.attendee, status=MemberStatus.approved))
    elif membership.status == MemberStatus.revoked:
        # An old invite link must not undo an organizer's revocation.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your access to this event was revoked")
    elif membership.status == MemberStatus.pending:
        membership.status = MemberStatus.approved
    invite.status = InviteStatus.accepted
    invite.accepted_by = user.id
    invite.accepted_at = utcnow()
    db.commit()
