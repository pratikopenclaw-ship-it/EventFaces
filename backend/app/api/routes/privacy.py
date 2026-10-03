"""Privacy features: delete my data, removal requests, search audit log."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.cookies import clear_auth_cookies
from app.api.deps import DB, CurrentUser, ManagedEvent, VerifiedUser
from app.api.selfie import REMOVAL_SUBMIT_OPENAPI, read_selfie, selfie_content_type
from app.core import rate_limit
from app.core.face_slots import face_slot
from app.core.email import Mail, get_mailer
from app.core.security import verify_password
from app.models import Event, RemovalRequest, RemovalStatus, SearchAudit, User
from app.services import imaging, mobile_auth, removal
from app.services.account import delete_account
from app.services.search import NoFaceFound

router = APIRouter(prefix="/api", tags=["privacy"])


# --- Delete my data ---------------------------------------------------------------------


class DeleteMeIn(BaseModel):
    """Re-authenticate with the password, or (accounts without one: app sign-in) with the
    code from POST /api/me/reauth-code."""

    password: str | None = Field(default=None, max_length=128)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")


@router.post("/me/reauth-code", status_code=status.HTTP_202_ACCEPTED)
def send_reauth_code(user: CurrentUser, background: BackgroundTasks) -> dict[str, str]:
    rate_limit.enforce(f"reauth-code:{user.id}", rate_limit.Limit(5, 3600))
    issued = mobile_auth.issue_code("reauth", str(user.id), with_magic_link=False)
    background.add_task(
        get_mailer().send,
        Mail(
            to=user.email,
            subject="Your EventFaces confirmation code",
            body=f"Your code to confirm deleting your account: {issued.code}\n\n"
            "It expires in a few minutes. If you didn't ask for it, you can ignore this email.\n",
        ),
    )
    return {"detail": "We've emailed you a code."}


@router.delete("/me")
def delete_me(body: DeleteMeIn, response: Response, user: CurrentUser, db: DB, background: BackgroundTasks) -> dict:
    rate_limit.enforce(f"delete-me:{user.id}", rate_limit.Limit(5, 3600))
    db.commit()  # no pooled connection held while hashing (SEC-041)
    if body.code is not None:
        confirmed = mobile_auth.check_code("reauth", str(user.id), body.code)
    elif body.password is not None and user.password_hash is not None:
        confirmed = verify_password(body.password, user.password_hash)
    else:
        confirmed = False
    if not confirmed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password or code is incorrect")
    email = user.email
    summary = delete_account(db, user)
    clear_auth_cookies(response)
    background.add_task(
        get_mailer().send,
        Mail(
            to=email,
            subject="Your EventFaces data was deleted",
            body="Your account and the data linked to it (event memberships, matched photos, uploads and invites) "
            "have been deleted. If you didn't do this, contact the event organizer.\n",
        ),
    )
    return {"deleted": summary.__dict__}


# --- Removal requests (public side) ---------------------------------------------------------


class RemovalCreateIn(BaseModel):
    event: str = Field(min_length=1, max_length=80, description="Event slug from the removal link")
    email: EmailStr
    message: str = Field(default="", max_length=2000)


class RemovalInfo(BaseModel):
    event_name: str
    event_date: dt.date | None


GENERIC = {"detail": "If that event exists, we've emailed you a link to continue your request."}


def _event_by_slug(db: Session, slug: str) -> Event | None:
    return db.scalar(select(Event).where(Event.slug == slug))


@router.get("/removal-requests/event/{slug}", response_model=RemovalInfo)
def removal_event_info(slug: str, request: Request, db: DB) -> RemovalInfo:
    rate_limit.enforce(f"removal-info:{rate_limit.client_ip(request)}", rate_limit.Limit(60, 600))
    event = _event_by_slug(db, slug)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return RemovalInfo(event_name=event.name, event_date=event.date)


@router.post("/removal-requests", status_code=status.HTTP_202_ACCEPTED)
def create_removal_request(body: RemovalCreateIn, request: Request, db: DB, background: BackgroundTasks) -> dict:
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"removal:ip:{ip}", rate_limit.Limit(5, 3600))
    rate_limit.enforce(f"removal:email:{body.email.lower()}", rate_limit.Limit(3, 86400))
    event = _event_by_slug(db, body.event)
    if event is not None:
        raw = removal.create_request(db, event, body.email, body.message)
        background.add_task(
            get_mailer().send,
            Mail(
                to=body.email,
                subject=f"Confirm your photo removal request for {event.name}",
                body=f"Open this link within 48 hours to continue your request:\n\n{removal.request_link(raw)}\n\n"
                "If you didn't ask for this, ignore this email.\n",
            ),
        )
    return GENERIC


@router.get("/removal-requests/{token}")
def removal_request_info(token: str, db: DB) -> dict:
    req = removal.find_open_request(db, token)
    event = db.get(Event, req.event_id)
    db.rollback()  # release the row lock
    return {"event_name": event.name if event else "", "email": req.email}


@router.post("/removal-requests/{token}/submit", openapi_extra=REMOVAL_SUBMIT_OPENAPI)
async def submit_removal_request(token: str, request: Request, db: DB, background: BackgroundTasks) -> dict:
    """Body: an image (reference selfie, optional) or empty to submit without one."""
    rate_limit.enforce(f"removal-submit:{rate_limit.client_ip(request)}", rate_limit.Limit(10, 3600))
    if not selfie_content_type(request):
        return await run_in_threadpool(_submit_sync, db, token, None, background)
    async with face_slot():  # shares the per-process face-work cap with searches (SEC-039)
        selfie = await read_selfie(request)
        try:
            return await run_in_threadpool(_submit_sync, db, token, selfie, background)
        finally:
            del selfie


def _submit_sync(db: Session, token: str, selfie: bytes | None, background: BackgroundTasks) -> dict:
    removal.find_open_request(db, token)  # validate the link before spending any CPU on it
    db.rollback()  # release the row lock and connection while the face model runs
    embedding = None
    if selfie:
        try:
            embedding = removal.reference_embedding(selfie)
        except imaging.UnsupportedImage as e:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
        except NoFaceFound as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    try:
        req = removal.find_open_request(db, token)  # re-lock: a parallel submit may have won
        removal.submit(db, req, embedding)
    finally:
        del embedding
    event = db.get(Event, req.event_id)
    for email in removal.organizer_emails(db, req.event_id):
        background.add_task(
            get_mailer().send,
            Mail(
                to=email,
                subject=f"Photo removal request for {event.name if event else 'your event'}",
                body="Someone who appears in your event's photos asked for them to be removed. "
                "Review it in the Moderation tab.\n",
            ),
        )
    # Deliberately no photo IDs or previews for the requester.
    return {"detail": "Thanks. The organizers will review your request and email you the outcome.", "submitted": True}


# --- Removal requests (organizer side) & search log ------------------------------------------


class RemovalOut(BaseModel):
    id: uuid.UUID
    email: str
    message: str
    status: RemovalStatus
    matched_photo_ids: list[uuid.UUID]
    created_at: dt.datetime


class RemovalResolveIn(BaseModel):
    action: Literal["remove", "decline"]
    photo_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


@router.get("/events/{event_id}/removal-requests", response_model=list[RemovalOut])
def list_removal_requests(event: ManagedEvent, db: DB) -> list[RemovalRequest]:
    return list(
        db.scalars(
            select(RemovalRequest)
            .where(RemovalRequest.event_id == event.id, RemovalRequest.status == RemovalStatus.submitted)
            .order_by(RemovalRequest.created_at)
        )
    )


@router.post("/events/{event_id}/removal-requests/{request_id}/resolve")
def resolve_removal_request(
    request_id: uuid.UUID, body: RemovalResolveIn, event: ManagedEvent, user: VerifiedUser, db: DB
) -> dict:
    req = db.get(RemovalRequest, request_id, with_for_update=True)
    if req is None or req.event_id != event.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    removed = removal.resolve(db, event, req, user, body.action, body.photo_ids)
    return {"removed": removed}


class SearchLogRow(BaseModel):
    user_email: str | None
    match_count: int
    created_at: dt.datetime


@router.get("/events/{event_id}/search-log", response_model=list[SearchLogRow])
def search_log(event: ManagedEvent, db: DB, limit: Annotated[int, Query(ge=1, le=1000)] = 200) -> list[SearchLogRow]:
    rows = db.execute(
        select(SearchAudit, User.email)
        .outerjoin(User, User.id == SearchAudit.user_id)
        .where(SearchAudit.event_id == event.id)
        .order_by(SearchAudit.created_at.desc())
        .limit(min(max(limit, 1), 1000))
    ).all()
    return [SearchLogRow(user_email=email, match_count=a.match_count, created_at=a.created_at) for a, email in rows]
