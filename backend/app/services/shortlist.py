"""An attendee's personal photo picks within an event ('I want this one'). Idempotent:
adding an already-shortlisted photo or removing one that isn't shortlisted is a no-op,
so the frontend's optimistic toggle never has to special-case a race."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Event, Photo, PhotoShortlist, User


def add(db: Session, event: Event, user: User, photo: Photo) -> None:
    stmt = insert(PhotoShortlist).values(id=uuid.uuid4(), user_id=user.id, photo_id=photo.id, event_id=event.id)
    db.execute(stmt.on_conflict_do_nothing(constraint="uq_photo_shortlists_user_photo"))
    db.commit()


def remove(db: Session, event: Event, user: User, photo_id: uuid.UUID) -> None:
    db.execute(
        delete(PhotoShortlist).where(
            PhotoShortlist.user_id == user.id,
            PhotoShortlist.photo_id == photo_id,
            PhotoShortlist.event_id == event.id,
        )
    )
    db.commit()


def shortlisted_photo_ids(db: Session, event: Event, user: User) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(PhotoShortlist.photo_id).where(PhotoShortlist.user_id == user.id, PhotoShortlist.event_id == event.id)
        )
    )
