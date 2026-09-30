import csv
import io
import uuid
from typing import Literal

import segno
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, ManagedEvent, VerifiedUser
from app.api.routes.auth import start_session
from app.core import rate_limit
from app.core.config import get_settings
from app.core.email import Mail, get_mailer
from app.core.security import hash_password
from app.models import Event, Invite, InviteStatus, JoinMode, User, UserRole
from app.schemas.auth import UserOut
from app.schemas.community import (
    InviteCsvIn,
    InviteOut,
    InvitePreview,
    InviteRegisterIn,
    InviteTokenIn,
    InviteUploadOut,
)
from app.schemas.event import EventPublicOut
from app.services import invites

router = APIRouter(prefix="/api", tags=["invites"])


def _send_invite(background: BackgroundTasks, event: Event, email: str, raw: str) -> None:
    background.add_task(
        get_mailer().send,
        Mail(to=email, subject=f"Your photos from {event.name}", body=invites.invite_email_body(event, raw)),
    )


# --- Organizer side ----------------------------------------------------------------


@router.post("/events/{event_id}/invites", response_model=InviteUploadOut)
def upload_invites(
    body: InviteCsvIn, event: ManagedEvent, user: VerifiedUser, db: DB, background: BackgroundTasks
) -> InviteUploadOut:
    rate_limit.enforce(f"invites:{event.id}", rate_limit.Limit(20, 3600))
    try:
        parsed = invites.parse_emails(body.csv)
    except csv.Error as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Couldn't read that CSV. Use one email per line or cell.") from e
    if not parsed.valid and not parsed.invalid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No email addresses found")
    outcome = invites.create_invites(db, event, user, parsed.valid)
    for email, raw in outcome.to_send:
        _send_invite(background, event, email, raw)
    return InviteUploadOut(
        sent=[e for e, _ in outcome.to_send],
        invalid=parsed.invalid,
        already_members=outcome.already_members,
        already_accepted=outcome.already_accepted,
    )


@router.get("/events/{event_id}/invites", response_model=list[InviteOut])
def list_invites(event: ManagedEvent, db: DB) -> list[Invite]:
    return list(db.scalars(select(Invite).where(Invite.event_id == event.id).order_by(Invite.created_at.desc())))


def _event_invite(db: DB, event_id: uuid.UUID, invite_id: uuid.UUID) -> Invite:
    invite = db.get(Invite, invite_id)
    if invite is None or invite.event_id != event_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    return invite


@router.post("/events/{event_id}/invites/{invite_id}/resend", response_model=InviteOut)
def resend_invite(invite_id: uuid.UUID, event: ManagedEvent, db: DB, background: BackgroundTasks) -> Invite:
    rate_limit.enforce(f"invite-resend:{invite_id}", rate_limit.Limit(5, 3600))
    invite = _event_invite(db, event.id, invite_id)
    if invite.status == InviteStatus.accepted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already accepted")
    raw = invites.rotate_token(db, event, invite)  # the old link stops working
    _send_invite(background, event, invite.email, raw)
    return invite


@router.delete("/events/{event_id}/invites/{invite_id}", response_model=InviteOut)
def revoke_invite(invite_id: uuid.UUID, event: ManagedEvent, db: DB) -> Invite:
    invite = _event_invite(db, event.id, invite_id)
    if invite.status == InviteStatus.pending:
        invite.status = InviteStatus.revoked
        db.commit()
    return invite


@router.get("/events/{event_id}/qr")
def join_qr(event: ManagedEvent, format: Literal["svg", "png"] = "svg") -> Response:
    """QR code of the event's join link (code-mode events). The link embeds the access code."""
    if event.join_mode != JoinMode.code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invite-only events use personal links, not a QR code")
    url = f"{get_settings().frontend_url}/join/{event.slug}?code={event.access_code}"
    qr = segno.make(url, error="m")
    out = io.BytesIO()
    headers = {"Cache-Control": "private, no-store"}
    if format == "png":
        qr.save(out, kind="png", scale=12, border=4)
        headers["Content-Disposition"] = f'attachment; filename="{event.slug}-qr.png"'
        return Response(out.getvalue(), media_type="image/png", headers=headers)
    qr.save(out, kind="svg", scale=8, border=4, dark="#1a1d24", xmldecl=False)
    return Response(out.getvalue(), media_type="image/svg+xml", headers=headers)


# --- Invitee side ---------------------------------------------------------------------


@router.get("/invites/{token}", response_model=InvitePreview)
def invite_preview(token: str, request: Request, db: DB) -> InvitePreview:
    rate_limit.enforce(f"invite-preview:{rate_limit.client_ip(request)}", rate_limit.Limit(60, 600))
    invite, event = invites.find_valid_invite(db, token)
    account = db.scalar(select(User.id).where(User.email == invite.email, User.deleted_at.is_(None)))
    db.rollback()  # release the row lock taken by find_valid_invite
    return InvitePreview(
        event_name=event.name,
        event_date=event.date,
        email=invite.email,
        account_exists=account is not None,
        accepted=invite.status == InviteStatus.accepted,
    )


@router.post("/invites/accept", response_model=EventPublicOut)
def accept_invite(body: InviteTokenIn, request: Request, user: CurrentUser, db: DB) -> Event:
    rate_limit.enforce(f"invite-accept:{rate_limit.client_ip(request)}", rate_limit.Limit(30, 600))
    invite, event = invites.find_valid_invite(db, body.token)
    invites.accept(db, invite, event, user)
    return event


@router.post("/invites/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_from_invite(body: InviteRegisterIn, request: Request, response: Response, db: DB) -> User:
    """Create an account for the invited email and accept the invite in one step."""
    rate_limit.enforce(f"invite-register:{rate_limit.client_ip(request)}", rate_limit.Limit(10, 3600))
    invite, event = invites.find_valid_invite(db, body.token)
    if db.scalar(select(User.id).where(User.email == invite.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email exists — log in to accept")
    user = User(email=invite.email, password_hash=hash_password(body.password), role=UserRole.attendee)
    db.add(user)
    db.flush()
    invites.accept(db, invite, event, user)  # also marks the email verified
    start_session(db, response, user)
    db.commit()
    return user
