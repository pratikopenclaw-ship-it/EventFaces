"""Guest uploads: presigned direct-to-storage PUT, then server-side validation + ingest.

1. start_upload   → photo row (processing) + presigned PUT locked to exact size & type
2. browser PUTs the file straight to storage (never through our API)
3. finish_upload  → verify object exists, size ≤ limit, magic bytes; set moderation state;
                    enqueue ingest (re-encode strips EXIF/GPS) → index_photo
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.config import get_settings
from app.models import Event, IndexStatus, ModerationMode, Photo, PhotoSource, PhotoStatus, User
from app.services import imaging

ALLOWED_TYPES = {"image/jpeg": "jpeg", "image/png": "png", "image/heic": "heif", "image/heif": "heif"}


def _require_enabled(event: Event) -> None:
    if not event.guest_upload_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Guest uploads are disabled for this event")


def _enforce_quotas(db: Session, event: Event, user: User) -> None:
    # Serialize upload starts per event (row lock) so concurrent requests can't overshoot.
    db.execute(select(Event.id).where(Event.id == event.id).with_for_update())
    live = (
        select(func.count())
        .select_from(Photo)
        .where(
            Photo.event_id == event.id,
            Photo.source == PhotoSource.guest,
            Photo.status.not_in([PhotoStatus.rejected, PhotoStatus.removed]),
        )
    )
    s = get_settings()
    if (db.scalar(live.where(Photo.uploaded_by == user.id)) or 0) >= s.guest_upload_max_per_user:
        raise HTTPException(status.HTTP_409_CONFLICT, "You've reached the upload limit for this event")
    if (db.scalar(live) or 0) >= s.guest_upload_max_per_event:
        raise HTTPException(status.HTTP_409_CONFLICT, "This event has reached its guest upload limit")


def start_upload(
    db: Session, event: Event, user: User, filename: str, content_type: str, size: int
) -> tuple[Photo, str]:
    _require_enabled(event)
    s = get_settings()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only JPEG, PNG and HEIC photos are allowed")
    if size <= 0 or size > s.guest_upload_max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Photos must be under {s.guest_upload_max_bytes // (1024 * 1024)} MB",
        )
    _enforce_quotas(db, event, user)
    photo = Photo(
        id=uuid.uuid4(),
        event_id=event.id,
        source=PhotoSource.guest,
        uploaded_by=user.id,
        original_filename=filename[:500],
        status=PhotoStatus.processing,
        index_status=IndexStatus.queued,
        upload_content_type=content_type,
    )
    photo.upload_key = storage.upload_key(event.id, photo.id)
    db.add(photo)
    db.commit()
    url = storage.presigned_put(photo.upload_key, content_type, size, s.upload_url_seconds)
    return photo, url


def _reject(db: Session, photo: Photo, code: int, message: str) -> HTTPException:
    storage.delete_keys(photo.upload_key)
    photo.upload_key = None
    photo.status = PhotoStatus.rejected
    photo.index_status = IndexStatus.failed
    photo.error = message
    db.commit()
    return HTTPException(code, message)


def finish_upload(db: Session, event: Event, user: User, photo_id: uuid.UUID) -> Photo:
    _require_enabled(event)
    photo = db.get(Photo, photo_id, with_for_update=True)
    if photo is None or photo.event_id != event.id or photo.uploaded_by != user.id or photo.source != PhotoSource.guest:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    if photo.upload_key is None or photo.index_status != IndexStatus.queued or photo.status != PhotoStatus.processing:
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload was already completed")

    size = storage.head_size(photo.upload_key)
    if size is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The file hasn't arrived in storage yet")
    if size > get_settings().guest_upload_max_bytes:
        raise _reject(db, photo, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")
    # Don't trust the declared content type: check the actual bytes.
    try:
        kind = imaging.sniff_type(storage.get_range(photo.upload_key, 0, 31))
    except imaging.UnsupportedImage as e:
        raise _reject(db, photo, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    if kind != ALLOWED_TYPES.get(photo.upload_content_type or ""):
        raise _reject(db, photo, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File content doesn't match its type")

    # Unapproved photos never become searchable: manual moderation parks them in review.
    if event.moderation_mode == ModerationMode.manual:
        photo.status = PhotoStatus.pending_review
    photo.index_status = IndexStatus.importing  # makes a second "complete" call a 409
    db.commit()
    return photo
