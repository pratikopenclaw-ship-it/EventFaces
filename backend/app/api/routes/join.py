from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import DB, VerifiedUser
from app.core import rate_limit
from app.core.config import get_settings
from app.core.security import constant_time_equals, utcnow
from app.models import Event, EventMember, JoinMode, MemberRole, MemberStatus
from app.schemas.event import CodeOnlyJoinIn, EventPublicOut, JoinIn, JoinPreviewOut
from app.services.billing import limits
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

    event = _admit(db, event, user)
    rate_limit.clear_failures(lock_keys[0])  # only after a successful join, as before
    return event


def _admit(db: DB, event: Event, user: VerifiedUser) -> Event:
    """Membership for a correct code: the same rules for slug+code and code-only joins."""
    if event.join_mode != JoinMode.code:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This event is invite-only")
    if event.access_expires_at is not None and event.access_expires_at <= utcnow():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access to this event has ended")

    limits.ensure_attendee_room(db, event, user)  # plan limit (paid events)
    # Insert-if-absent atomically (a double-clicked join must not hit the primary key),
    # then lock whatever row exists and apply the rules to it.
    db.execute(
        pg_insert(EventMember)
        .values(event_id=event.id, user_id=user.id, role=MemberRole.attendee, status=MemberStatus.approved)
        .on_conflict_do_nothing(index_elements=["event_id", "user_id"])
    )
    membership = db.get(EventMember, (event.id, user.id), with_for_update=True, populate_existing=True)
    if membership is None:  # deleted by an organizer between the two statements
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Please try again")
    if membership.status == MemberStatus.revoked:
        db.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your access to this event was revoked")
    if membership.status == MemberStatus.pending:
        membership.status = MemberStatus.approved
    db.commit()
    return event


@router.post("/by-code", response_model=EventPublicOut)
def join_with_code_only(body: CodeOnlyJoinIn, request: Request, user: VerifiedUser, db: DB) -> Event:
    """Join with just the access code (typed in the app). One endpoint covers every event,
    so the lockout is global per user and per IP rather than per event."""
    s = get_settings()
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"join:{ip}", rate_limit.Limit.parse(s.join_rate_limit))
    lock_keys = [f"join-code:{user.id}", f"join-code-ip:{ip}"]
    if any(rate_limit.is_locked(k, s.join_lockout_attempts) for k in lock_keys):
        raise LOCKED
    code = normalize_code(body.code)
    event = db.scalar(select(Event).where(Event.access_code == code))
    if event is None or not constant_time_equals(code, event.access_code):
        for k in lock_keys:
            rate_limit.record_failure(k, s.join_lockout_seconds)
        raise INVALID
    event = _admit(db, event, user)
    rate_limit.clear_failures(lock_keys[0])
    return event
