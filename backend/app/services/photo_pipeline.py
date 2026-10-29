"""Photo import + indexing steps, called from Celery tasks (and directly in tests).

Drive sync:   list folder → insert new `photos` rows (queued) → import each → index each
Guest upload: (Phase 4) finalize upload → index (same `index_photo`)
"""

import io
import logging
import uuid
from collections.abc import Callable
from typing import Any
from datetime import datetime, timedelta

from PIL import Image
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import storage
from app.core.config import get_settings
from app.core.security import utcnow
from app.models import (
    DriveSyncRun,
    Event,
    Face,
    IndexStatus,
    Photo,
    PhotoSource,
    PhotoStatus,
    SearchGrant,
    SyncStatus,
)
from app.services import imaging
from app.services.billing import limits
from app.services.drive import DriveAccessError, DriveFileTooLarge, get_drive_client
from app.services.faces import current_model_id, detect_faces

log = logging.getLogger(__name__)

Enqueue = Callable[[uuid.UUID], None]


class PermanentError(Exception):
    """A failure that retrying won't fix (bad file, too large, not an image)."""


def _truncate(msg: str, limit: int = 500) -> str:
    return msg if len(msg) <= limit else msg[: limit - 1] + "…"


# --- Drive sync ---------------------------------------------------------------


def active_sync_run(db: Session, event_id: uuid.UUID) -> DriveSyncRun | None:
    """A queued/running run that isn't stale (so a crashed worker can't block syncing forever)."""
    stale_before = utcnow() - timedelta(minutes=get_settings().drive_sync_stale_minutes)
    return db.scalar(
        select(DriveSyncRun)
        .where(
            DriveSyncRun.event_id == event_id,
            DriveSyncRun.status.in_([SyncStatus.queued, SyncStatus.running]),
            DriveSyncRun.created_at > stale_before,
        )
        .order_by(DriveSyncRun.created_at.desc())
        .limit(1)
    )


def _new_files_only(db: Session, event: Event, page: list[Any]) -> list[Any]:
    known = set(
        db.scalars(
            select(Photo.drive_file_id).where(Photo.event_id == event.id, Photo.drive_file_id.in_([f.id for f in page]))
        )
    )
    return [f for f in page if f.id not in known]


def run_drive_sync(db: Session, run_id: uuid.UUID, enqueue_import: Enqueue) -> None:
    run = db.get(DriveSyncRun, run_id)
    if run is None:
        return
    event = db.get(Event, run.event_id)
    if event is None:
        return
    run.status = SyncStatus.running
    run.started_at = utcnow()
    db.commit()

    new_ids: list[uuid.UUID] = []
    retry_ids: list[uuid.UUID] = []
    try:
        for listed in get_drive_client().list_images(run.folder_id):
            run.files_listed += len(listed)
            page = listed
            room = limits.photo_room(db, event)  # plan limit; None = unlimited
            if room is not None and len(page) > room:
                # Files already imported are skipped by the unique constraint below, so a
                # re-sync can still count them; only files that would be new are cut off.
                page = _new_files_only(db, event, page)
                run.files_over_limit += max(0, len(page) - room)
                page = page[:room]
            if page:
                inserted = db.scalars(
                    insert(Photo)
                    .values(
                        [
                            {
                                "id": uuid.uuid4(),
                                "event_id": event.id,
                                "source": PhotoSource.drive,
                                "drive_file_id": f.id,
                                "original_filename": f.name[:500],
                                "status": PhotoStatus.processing,
                                "index_status": IndexStatus.queued,
                            }
                            for f in page
                        ]
                    )
                    .on_conflict_do_nothing(constraint="uq_photos_event_drive_file")
                    .returning(Photo.id)
                ).all()
                new_ids.extend(inserted)
                run.files_new += len(inserted)
            db.commit()

        # Retry photos that failed transiently in earlier runs (permanently bad files
        # are `rejected` and skipped).
        retry_ids = list(
            db.scalars(
                update(Photo)
                .where(
                    Photo.event_id == event.id,
                    Photo.source == PhotoSource.drive,
                    Photo.index_status == IndexStatus.failed,
                    Photo.status == PhotoStatus.processing,
                )
                .values(index_status=IndexStatus.queued, error=None)
                .returning(Photo.id)
            ).all()
        )
        run.files_retried = len(retry_ids)
        run.status = SyncStatus.completed
        run.finished_at = utcnow()
        db.commit()
    except DriveAccessError as e:
        db.rollback()
        _fail_run(db, run_id, str(e))
        return
    except Exception as e:
        db.rollback()
        log.exception("Drive sync %s failed", run_id)
        _fail_run(db, run_id, f"Sync failed: {e}")
        # Photos inserted before the failure are still imported below.

    for photo_id in [*new_ids, *retry_ids]:
        enqueue_import(photo_id)


def _fail_run(db: Session, run_id: uuid.UUID, message: str) -> None:
    run = db.get(DriveSyncRun, run_id)
    if run is not None:
        run.status = SyncStatus.failed
        run.error = _truncate(message)
        run.finished_at = utcnow()
        db.commit()


def import_drive_photo(db: Session, photo_id: uuid.UUID, enqueue_index: Enqueue) -> None:
    """Download from Drive, re-encode (strips metadata), store original/preview/thumb."""
    photo = db.get(Photo, photo_id)
    if photo is None or photo.drive_file_id is None or photo.index_status == IndexStatus.indexed:
        return
    photo.index_status = IndexStatus.importing
    db.commit()

    try:
        data = get_drive_client().download(photo.drive_file_id, get_settings().max_import_bytes)
        processed = imaging.process(data)
    except (DriveFileTooLarge, imaging.UnsupportedImage) as e:
        raise PermanentError(str(e)) from e

    keys = {v: storage.photo_key(photo.event_id, photo.id, v) for v in ("original", "preview", "thumb")}
    storage.put_jpeg(keys["original"], processed.original)
    storage.put_jpeg(keys["preview"], processed.preview)
    storage.put_jpeg(keys["thumb"], processed.thumb)

    photo.original_key = keys["original"]
    photo.preview_key = keys["preview"]
    photo.thumb_key = keys["thumb"]
    photo.width, photo.height = processed.width, processed.height
    photo.sha256 = processed.sha256
    photo.index_status = IndexStatus.indexing
    db.commit()
    enqueue_index(photo.id)


# --- Indexing (shared by Drive and guest uploads) --------------------------------


def publish(photo: Photo) -> None:
    """Make a photo live. The only way to publish (tests/test_photo_alerts.py): new-photo
    alerts batch on published_at, so no path may set the status without it."""
    photo.status = PhotoStatus.published
    photo.published_at = utcnow()


def index_photo(db: Session, photo_id: uuid.UUID) -> int:
    """Detect all faces in the stored original and replace the photo's embeddings.

    Idempotent: re-indexing deletes the old face rows first. Returns the face count.
    """
    photo = db.get(Photo, photo_id)
    if photo is None or photo.original_key is None:
        return 0
    photo.index_status = IndexStatus.indexing
    db.commit()

    img = Image.open(io.BytesIO(storage.get_bytes(photo.original_key))).convert("RGB")
    faces = detect_faces(img)
    model = current_model_id()

    # Detection is slow; the photo may have been rejected/removed meanwhile. Re-read it
    # under a row lock (moderation takes the same lock) and never write embeddings for
    # a retired photo.
    db.refresh(photo, with_for_update=True)
    if photo.original_key is None or photo.status in (PhotoStatus.rejected, PhotoStatus.removed):
        db.rollback()
        return 0
    event = db.get(Event, photo.event_id)
    if event is None or event.retention_completed_at is not None:
        # The event's face data was deleted by retention; don't recreate it.
        photo.index_status = IndexStatus.indexed
        photo.face_count = 0
        db.commit()
        return 0

    db.execute(delete(Face).where(Face.photo_id == photo.id))
    db.add_all(
        Face(
            photo_id=photo.id,
            event_id=photo.event_id,
            bbox=list(f.bbox),
            det_score=f.det_score,
            embedding=f.embedding.tolist(),
            model=model,
        )
        for f in faces
    )
    photo.face_count = len(faces)
    if faces:
        # Shared photos must never show a face to everyone (services/sharing.py).
        photo.shared_at = photo.shared_by = None
    photo.index_status = IndexStatus.indexed
    photo.indexed_at = utcnow()
    photo.error = None
    if photo.status == PhotoStatus.processing:
        # Drive photos and auto-moderated guest uploads go live once indexed. Guest uploads
        # under manual moderation are `pending_review` and wait for an organizer. A photo
        # with no detected face is held the same way when the event opts out of
        # auto-publishing faceless photos, regardless of source or moderation mode.
        if len(faces) == 0 and not event.auto_publish_faceless_photos:
            photo.status = PhotoStatus.pending_review
        else:
            publish(photo)
    db.commit()
    return len(faces)


def ingest_guest_upload(db: Session, photo_id: uuid.UUID, enqueue_index: Enqueue) -> None:
    """Re-encode a guest's raw upload (strips EXIF/GPS), store variants, delete the raw object."""
    photo = db.get(Photo, photo_id)
    if photo is None or photo.upload_key is None or photo.original_key is not None:
        return

    data = storage.get_bytes(photo.upload_key)
    if len(data) > get_settings().guest_upload_max_bytes:
        raise PermanentError("File is too large")
    try:
        processed = imaging.process(data)
    except imaging.UnsupportedImage as e:
        raise PermanentError(str(e)) from e
    del data

    keys = {v: storage.photo_key(photo.event_id, photo.id, v) for v in ("original", "preview", "thumb")}
    for variant, key in keys.items():
        storage.put_jpeg(key, getattr(processed, variant))
    storage.delete_keys(photo.upload_key)

    photo.upload_key = None
    photo.original_key, photo.preview_key, photo.thumb_key = keys["original"], keys["preview"], keys["thumb"]
    photo.width, photo.height = processed.width, processed.height
    photo.sha256 = processed.sha256
    photo.index_status = IndexStatus.indexing
    db.commit()
    enqueue_index(photo.id)


def retire_photo(db: Session, photo: Photo, status: PhotoStatus) -> None:
    """Take a photo out of circulation (rejected/removed): delete its face embeddings,
    everyone's grants to it, and all stored image data. The row stays as a tombstone so
    Drive re-syncs don't re-import it and moderation history is kept."""
    db.execute(delete(Face).where(Face.photo_id == photo.id))
    db.execute(delete(SearchGrant).where(SearchGrant.photo_id == photo.id))
    storage.delete_keys(photo.upload_key, photo.original_key, photo.preview_key, photo.thumb_key)
    photo.upload_key = photo.original_key = photo.preview_key = photo.thumb_key = None
    photo.face_count = 0
    photo.shared_at = photo.shared_by = None
    photo.status = status


def mark_failed(db: Session, photo_id: uuid.UUID, message: str, permanent: bool = False) -> None:
    db.rollback()
    photo = db.get(Photo, photo_id)
    if photo is not None:
        photo.index_status = IndexStatus.failed
        photo.error = _truncate(message)
        if permanent:
            retire_photo(db, photo, PhotoStatus.rejected)  # never searchable; not retried by sync
        db.commit()


def cleanup_abandoned_uploads(db: Session, now: datetime | None = None) -> int:
    """Delete guest uploads that were started but never completed, and raw upload objects
    nothing references any more.

    Once the presigned URL has expired the file can no longer arrive, so after that
    (plus a grace period) the placeholder row and any partial object are removed. A URL
    stays valid after its upload was ingested or rejected, so a second PUT can recreate
    the raw object (with its original metadata, e.g. GPS); those orphans are swept too.
    """
    cutoff = (now or utcnow()) - timedelta(seconds=get_settings().upload_url_seconds) - timedelta(hours=1)
    stale = db.scalars(
        select(Photo).where(
            Photo.source == PhotoSource.guest,
            Photo.index_status == IndexStatus.queued,
            Photo.original_key.is_(None),
            Photo.created_at < cutoff,
        )
    ).all()
    for photo in stale:
        storage.delete_keys(photo.upload_key)
        db.delete(photo)
    db.commit()

    referenced = set(db.scalars(select(Photo.upload_key).where(Photo.upload_key.is_not(None))))
    for event_id in db.scalars(select(Event.id)):
        orphans = [
            key
            for key, modified in storage.list_objects(storage.uploads_prefix(event_id))
            if key not in referenced and modified < cutoff
        ]
        storage.delete_keys(*orphans)
    return len(stale)
