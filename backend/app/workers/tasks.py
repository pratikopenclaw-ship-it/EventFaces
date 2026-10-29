import logging
import uuid

from app.core import monitoring, storage
from app.core.config import get_settings
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
def import_drive_photo(self, photo_id: str) -> None:
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
def ingest_upload(self, photo_id: str) -> None:
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
def index_photo(self, photo_id: str) -> None:
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
        result = asdict(_run(db))
    # Only after a run that completed: a crashing run stops the check-ins and GlitchTip alerts.
    monitoring.heartbeat(get_settings().retention_heartbeat_url)
    return result


@celery_app.task(name="billing.maintenance")
def billing_maintenance() -> dict[str, int]:
    """Cancel abandoned checkouts (orders and add-on orders); end or renew subscriptions at
    their period end."""
    from app.services.billing import addon_orders, orders

    with SessionLocal() as db:
        result = orders.run_maintenance(db)
        result["addon_abandoned"] = addon_orders.run_maintenance(db)["abandoned"]
        return result


@celery_app.task(name="storage.delete_event_objects")
def delete_event_objects(event_id: str) -> int:
    return storage.delete_prefix(storage.event_prefix(event_id))


@celery_app.task(name="alerts.new_photos")
def new_photo_alerts() -> int:
    """Tell attendees who searched an event that new photos went live (one push + one email
    per batch, at most daily). Returns how many people were notified."""
    from app.core.security import utcnow
    from app.services import photo_alerts

    with SessionLocal() as db:
        return photo_alerts.run(db, utcnow())
