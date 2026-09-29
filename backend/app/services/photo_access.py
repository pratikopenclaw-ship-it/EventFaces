"""Who may view/download a photo. The caller must already have checked event membership.

- Organizers of the event (and super admins): any non-removed photo in the event.
- Attendees: only *published* photos they matched (unexpired grant) or uploaded.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import Event, Photo, PhotoStatus, SearchGrant, User
from app.services.membership import can_manage


def viewable_photos(db: Session, event: Event, user: User, photo_ids: Iterable[uuid.UUID]) -> list[Photo]:
    """The subset of `photo_ids` the user may see, in the order given."""
    ids = list(dict.fromkeys(photo_ids))
    if not ids:
        return []
    photos = {
        p.id: p
        for p in db.scalars(
            select(Photo).where(
                Photo.id.in_(ids),
                Photo.event_id == event.id,  # never cross event boundaries
                Photo.status != PhotoStatus.removed,
            )
        )
    }
    if not can_manage(db, event, user):
        granted = set(
            db.scalars(
                select(SearchGrant.photo_id).where(
                    SearchGrant.user_id == user.id,
                    SearchGrant.event_id == event.id,
                    SearchGrant.photo_id.in_(ids),
                    SearchGrant.expires_at > utcnow(),
                )
            )
        )
        photos = {
            pid: p
            for pid, p in photos.items()
            if p.status == PhotoStatus.published and (pid in granted or p.uploaded_by == user.id)
        }
    return [photos[i] for i in ids if i in photos]


def viewable_photo(db: Session, event: Event, user: User, photo_id: uuid.UUID) -> Photo | None:
    found = viewable_photos(db, event, user, [photo_id])
    return found[0] if found else None
