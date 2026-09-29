from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import DB, VerifiedUser
from app.core import rate_limit
from app.core.config import get_settings
from app.core.security import constant_time_equals, utcnow
from app.models import Event, EventMember, JoinMode, MemberRole, MemberStatus
from app.schemas.event import EventPublicOut, JoinIn, JoinPreviewOut
from app.services.events import normalize_code

router = APIRouter(prefix="/api/join", tags=["join"])

INVALID = HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid event link or access code")
LOCKED = HTTPException(
    status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong codes. Please try again later."
)


def _event_by_slug(db: DB, slug: str) -> Event | None:
    return db.scalar(select(Event).where(Event.slug == slug))


@router.get("/{slug}", response_model=JoinPreviewOut)
def join_preview(slug: str, request: Request, user: VerifiedUser, db: DB) -> Event:
    rate_limit.enforce(
        f"join-preview:{rate_limit.client_ip(request)}",
        rate_limit.Limit.parse(get_settings().join_rate_limit),
    )
    event = _event_by_slug(db, slug)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return event


@router.post("", response_model=EventPublicOut)
def join_by_code(body: JoinIn, request: Request, user: VerifiedUser, db: DB) -> Event:
    s = get_settings()
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"join:{ip}", rate_limit.Limit.parse(s.join_rate_limit))

    # Lock out per user+event and per IP+event, so neither switching accounts nor
    # switching networks gives unlimited guesses.
    lock_keys = [f"join:{user.id}:{body.slug}", f"join-ip:{ip}:{body.slug}"]
    if any(rate_limit.is_locked(k, s.join_lockout_attempts) for k in lock_keys):
        raise LOCKED

    event = _event_by_slug(db, body.slug)
    if event is None or not constant_time_equals(normalize_code(body.code), event.access_code):
        for k in lock_keys:
            rate_limit.record_failure(k, s.join_lockout_seconds)
        raise INVALID

    if event.join_mode != JoinMode.code:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This event is invite-only")
    if event.access_expires_at is not None and event.access_expires_at <= utcnow():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access to this event has ended")

    rate_limit.clear_failures(lock_keys[0])
    membership = db.get(EventMember, (event.id, user.id))
    if membership is None:
        db.add(
            EventMember(
                event_id=event.id,
                user_id=user.id,
                role=MemberRole.attendee,
                status=MemberStatus.approved,
            )
        )
    elif membership.status == MemberStatus.revoked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your access to this event was revoked")
    elif membership.status == MemberStatus.pending:
        membership.status = MemberStatus.approved
    db.commit()
    return event
