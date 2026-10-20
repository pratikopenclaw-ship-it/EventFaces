"""Organizer-shared photos: published photos with no detected face (food, venue, scenery)
that every approved member of the event may view, without a selfie match.

Only photos that carry no biometric data qualify: published, indexed, face_count == 0 and
no face rows. `photo_access.viewable_photos` re-checks face_count, `index_photo` clears the
flag when a re-index finds faces, and `retire_photo` clears it when a photo is taken out of
circulation. Sharing is always an explicit organizer action (the detector can miss people
seen from behind or far away), never automatic.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import Event, Face, IndexStatus, Photo, PhotoStatus, User


class SharingUnavailable(Exception):
    """The event's face data was deleted by retention, so "no face" can't be established."""


def shareable_clause() -> ColumnElement[bool]:
    """SQL condition for a photo that may be shared (used for listing and bulk sharing)."""
    return (
        (Photo.status == PhotoStatus.published)
        & (Photo.index_status == IndexStatus.indexed)
        & (Photo.face_count == 0)
        & Photo.original_key.is_not(None)
        & ~exists().where(Face.photo_id == Photo.id)
    )


def _check_event(event: Event) -> None:
    if event.retention_completed_at is not None:
        raise SharingUnavailable("This event's face data has expired, so photos can't be shared any more")


def set_shared(db: Session, event: Event, user: User, photo_ids: Iterable[uuid.UUID], shared: bool) -> tuple[int, int]:
    """Share or unshare photos of this event. Returns (changed, skipped): skipped counts IDs
    that don't qualify (faces found, not published, another event's or unknown)."""
    ids = list(dict.fromkeys(photo_ids))
    if shared:
        _check_event(event)
    where = [Photo.event_id == event.id, Photo.id.in_(ids)]
    if shared:
        where.append(shareable_clause())
    # Row locks: index_photo and moderation take the same lock, so a re-index can't race this.
    photos = db.scalars(select(Photo).where(*where).with_for_update()).all()
    changed = 0
    for photo in photos:
        if shared and photo.shared_at is None:
            photo.shared_at, photo.shared_by = utcnow(), user.id
            changed += 1
        elif not shared and photo.shared_at is not None:
            photo.shared_at = photo.shared_by = None
            changed += 1
    db.commit()
    return changed, len(ids) - len(photos)


def share_all_faceless(db: Session, event: Event, user: User) -> int:
    """Share every qualifying photo of the event that isn't shared yet. Returns how many."""
    _check_event(event)
    photos = db.scalars(
        select(Photo)
        .where(Photo.event_id == event.id, Photo.shared_at.is_(None), shareable_clause())
        .with_for_update()
    ).all()
    now = utcnow()
    for photo in photos:
        photo.shared_at, photo.shared_by = now, user.id
    db.commit()
    return len(photos)


def shared_photos(db: Session, event: Event, offset: int, limit: int) -> list[Photo]:
    return list(
        db.scalars(
            select(Photo)
            .where(
                Photo.event_id == event.id,
                Photo.status == PhotoStatus.published,
                Photo.face_count == 0,
                Photo.shared_at.is_not(None),
            )
            .order_by(Photo.created_at.desc(), Photo.id)
            .offset(offset)
            .limit(limit)
        )
    )
