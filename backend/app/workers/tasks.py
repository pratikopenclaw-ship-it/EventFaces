import logging
import uuid

from app.core import storage
from app.core.db import SessionLocal
from app.services import photo_pipeline
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

MAX_RETRIES = 4


def _backoff(retries: int) -> int:
    return min(300, 15 * 2**retries)


@celery_app.task(name="drive.sync", acks_late=True)
def sync_drive(run_id: str) -> None:
    with SessionLocal() as db:
        photo_pipeline.run_drive_sync(
            db, uuid.UUID(run_id), enqueue_import=lambda pid: import_drive_photo.delay(str(pid))
        )


@celery_app.task(name="drive.import_photo", bind=True, max_retries=MAX_RETRIES, acks_late=True)
def import_drive_photo(self, photo_id: str) -> None:  # type: ignore[no-untyped-def]
    pid = uuid.UUID(photo_id)
    with SessionLocal() as db:
        try:
            photo_pipeline.import_drive_photo(db, pid, enqueue_index=lambda p: index_photo.delay(str(p)))
        except photo_pipeline.PermanentError as e:
            photo_pipeline.mark_failed(db, pid, str(e), permanent=True)
        except Exception as e:
            if self.request.retries >= MAX_RETRIES:
                log.exception("Import of photo %s failed permanently", photo_id)
                photo_pipeline.mark_failed(db, pid, f"Import failed: {e}")
                return
            db.rollback()
            raise self.retry(exc=e, countdown=_backoff(self.request.retries)) from e


@celery_app.task(name="photos.ingest_upload", bind=True, max_retries=MAX_RETRIES, acks_late=True)
def ingest_upload(self, photo_id: str) -> None:  # type: ignore[no-untyped-def]
    pid = uuid.UUID(photo_id)
    with SessionLocal() as db:
        try:
            photo_pipeline.ingest_guest_upload(db, pid, enqueue_index=lambda p: index_photo.delay(str(p)))
        except photo_pipeline.PermanentError as e:
            photo_pipeline.mark_failed(db, pid, str(e), permanent=True)
        except Exception as e:
            if self.request.retries >= MAX_RETRIES:
                log.exception("Ingest of upload %s failed permanently", photo_id)
                photo_pipeline.mark_failed(db, pid, f"Processing failed: {e}")
                return
            db.rollback()
            raise self.retry(exc=e, countdown=_backoff(self.request.retries)) from e


@celery_app.task(name="photos.index", bind=True, max_retries=2, acks_late=True)
def index_photo(self, photo_id: str) -> None:  # type: ignore[no-untyped-def]
    pid = uuid.UUID(photo_id)
    with SessionLocal() as db:
        try:
            photo_pipeline.index_photo(db, pid)
        except Exception as e:
            if self.request.retries >= 2:
                log.exception("Indexing photo %s failed", photo_id)
                photo_pipeline.mark_failed(db, pid, f"Indexing failed: {e}")
                return
            db.rollback()
            raise self.retry(exc=e, countdown=_backoff(self.request.retries)) from e


@celery_app.task(name="photos.cleanup_abandoned_uploads")
def cleanup_abandoned_uploads() -> int:
    with SessionLocal() as db:
        return photo_pipeline.cleanup_abandoned_uploads(db)


@celery_app.task(name="retention.run")
def run_retention() -> dict[str, int]:
    from dataclasses import asdict

    from app.services.retention import run_retention as _run

    with SessionLocal() as db:
        return asdict(_run(db))


@celery_app.task(name="storage.delete_event_objects")
def delete_event_objects(event_id: str) -> int:
    return storage.delete_prefix(storage.event_prefix(event_id))
