"""Plan limits per event (attendees, photos). NULL limits mean unlimited (admin-created
events). Checks lock the event row, so concurrent joins or uploads can't overshoot."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Event, EventMember, MemberRole, MemberStatus, Photo, PhotoStatus, User

EVENT_FULL = HTTPException(
    status.HTTP_403_FORBIDDEN, "This event is full. Please ask the organizer to upgrade their plan."
)
PHOTO_LIMIT = HTTPException(status.HTTP_409_CONFLICT, "This event has reached its photo limit")

# Photos that count toward the limit: everything not rejected or removed.
_LIVE = Photo.status.not_in([PhotoStatus.rejected, PhotoStatus.removed])


def _lock(db: Session, event: Event) -> None:
    db.execute(select(Event.id).where(Event.id == event.id).with_for_update())


def attendee_count(db: Session, event: Event) -> int:
    return db.scalar(
        select(func.count())
        .select_from(EventMember)
        .where(
            EventMember.event_id == event.id,
            EventMember.role == MemberRole.attendee,
            EventMember.status != MemberStatus.revoked,
        )
    ) or 0


def photo_count(db: Session, event: Event) -> int:
    return db.scalar(select(func.count()).select_from(Photo).where(Photo.event_id == event.id, _LIVE)) or 0


def ensure_attendee_room(db: Session, event: Event, user: User) -> None:
    """Before admitting `user` as a new attendee. Existing rows are left to the caller
    (pending ones are approved, revoked ones refused with their own message)."""
    if event.max_attendees is None:
        return
    _lock(db, event)
    if db.get(EventMember, (event.id, user.id)) is not None:
        return
    if attendee_count(db, event) >= event.max_attendees:
        db.rollback()
        raise EVENT_FULL


def photo_room(db: Session, event: Event) -> int | None:
    """How many more photos the plan allows (None = unlimited). Locks the event row."""
    if event.max_photos is None:
        return None
    _lock(db, event)
    return max(0, event.max_photos - photo_count(db, event))
