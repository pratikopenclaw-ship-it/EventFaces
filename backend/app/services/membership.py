"""Single source of truth for "may this user act on this event?"."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import Event, EventMember, MemberRole, MemberStatus, User, UserRole


def get_membership(db: Session, event: Event, user: User) -> EventMember | None:
    return db.get(EventMember, (event.id, user.id))


def _not_expired(ts: datetime | None, now: datetime) -> bool:
    return ts is None or ts > now


def is_active_member(event: Event, membership: EventMember | None) -> bool:
    """Approved and not expired. The event-wide access window applies to attendees only;
    organizers keep access after it ends so they can manage retention and deletion."""
    if membership is None or membership.status != MemberStatus.approved:
        return False
    now = utcnow()
    if not _not_expired(membership.expires_at, now):
        return False
    # The event-wide access window only binds attendees.
    return membership.role != MemberRole.attendee or _not_expired(event.access_expires_at, now)


def can_manage(db: Session, event: Event, user: User) -> bool:
    if user.role == UserRole.super_admin:
        return True
    if user.role != UserRole.organizer:
        return False
    m = get_membership(db, event, user)
    return m is not None and m.role == MemberRole.organizer and is_active_member(event, m)


def can_access(db: Session, event: Event, user: User) -> bool:
    if user.role == UserRole.super_admin:
        return True
    return is_active_member(event, get_membership(db, event, user))
