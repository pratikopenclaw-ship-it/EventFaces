import re
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Event, EventMember, MemberRole, Photo, PhotoStatus, User, UserRole
from app.services.membership import can_manage, is_active_member

# No 0/O/1/I to keep codes easy to read aloud and type.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def generate_access_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", code).upper()


def generate_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "event"
    suffix = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(6))
    return f"{base}-{suffix}"


def list_events_for(db: Session, user: User) -> list[tuple[Event, EventMember | None, bool]]:
    """Events visible to the user as (event, membership, can_manage), newest first."""
    if user.role == UserRole.super_admin:
        events = db.scalars(select(Event).order_by(Event.date.desc().nulls_last(), Event.created_at.desc()))
        memberships = {
            m.event_id: m for m in db.scalars(select(EventMember).where(EventMember.user_id == user.id))
        }
        return [(e, memberships.get(e.id), True) for e in events]

    rows = db.execute(
        select(Event, EventMember)
        .join(EventMember, EventMember.event_id == Event.id)
        .where(EventMember.user_id == user.id)
        .order_by(Event.date.desc().nulls_last(), Event.created_at.desc())
    ).all()
    result = []
    for event, m in rows:
        if not is_active_member(event, m):
            continue
        manage = m.role == MemberRole.organizer and can_manage(db, event, user)
        result.append((event, m, manage))
    return result


def photo_counts(db: Session, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Published photo count per event."""
    if not event_ids:
        return {}
    rows = db.execute(
        select(Photo.event_id, func.count())
        .where(Photo.event_id.in_(event_ids), Photo.status == PhotoStatus.published)
        .group_by(Photo.event_id)
    ).all()
    return dict(rows)
