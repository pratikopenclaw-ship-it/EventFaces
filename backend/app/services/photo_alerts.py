"""New-photo alerts (Part 1): attendees who searched an event hear when new photos with
faces go live there, so they scan again. Nothing biometric is stored: a search only leaves
an `event_photo_alerts` row saying when the user last searched the event
(docs/superpowers/specs/2026-10-20-new-photo-alerts-design.md). Rows never reach organizer
or admin views."""

import uuid
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import EventPhotoAlert, Photo, PhotoStatus


def _qualifying_after(event_id: uuid.UUID, since: datetime):  # type: ignore[no-untyped-def]
    """Live photos with faces that went live after `since` (faceless photos never count)."""
    return (
        Photo.event_id == event_id,
        Photo.status == PhotoStatus.published,
        Photo.face_count > 0,
        Photo.published_at > since,
    )


def record_search(db: Session, user_id: uuid.UUID, event_id: uuid.UUID, now: datetime) -> None:
    """Subscribe on search (or move the watermark on). Keeps an earlier opt-out. No commit."""
    stmt = insert(EventPhotoAlert).values(user_id=user_id, event_id=event_id, last_searched_at=now)
    db.execute(stmt.on_conflict_do_update(index_elements=["user_id", "event_id"], set_={"last_searched_at": now}))


def get(db: Session, user_id: uuid.UUID, event_id: uuid.UUID) -> EventPhotoAlert | None:
    return db.get(EventPhotoAlert, (user_id, event_id))


def has_new_photos(db: Session, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    """The banner: qualifying photos went live after the user's last search. Independent of
    the notification watermark and the opt-outs (it only shows inside the app)."""
    row = get(db, user_id, event_id)
    if row is None:
        return False
    return bool(db.scalar(select(exists().where(*_qualifying_after(event_id, row.last_searched_at)))))
