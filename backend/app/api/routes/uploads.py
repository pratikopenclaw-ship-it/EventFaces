import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import DB, MemberEvent, VerifiedUser
from app.core import rate_limit
from app.core.config import get_settings
from app.models import IndexStatus, Photo, PhotoSource, PhotoStatus
from app.schemas.community import MyUploadOut, UploadStartIn, UploadStartOut
from app.services import uploads
from app.workers.tasks import ingest_upload

router = APIRouter(prefix="/api/events/{event_id}", tags=["uploads"])


@router.post("/uploads", response_model=UploadStartOut, status_code=status.HTTP_201_CREATED)
def start_upload(body: UploadStartIn, event: MemberEvent, user: VerifiedUser, db: DB) -> UploadStartOut:
    rate_limit.enforce(f"upload:{user.id}", rate_limit.Limit.parse(get_settings().guest_upload_rate_limit))
    photo, url = uploads.start_upload(db, event, user, body.filename, body.content_type, body.size)
    return UploadStartOut(
        photo_id=photo.id,
        upload_url=url,
        content_type=body.content_type,
        expires_in=get_settings().upload_url_seconds,
    )


@router.post("/uploads/{photo_id}/complete", response_model=MyUploadOut)
def complete_upload(photo_id: uuid.UUID, event: MemberEvent, user: VerifiedUser, db: DB) -> Photo:
    photo = uploads.finish_upload(db, event, user, photo_id)
    ingest_upload.delay(str(photo.id))
    db.refresh(photo)
    return photo


@router.get("/my-uploads", response_model=list[MyUploadOut])
def my_uploads(event: MemberEvent, user: VerifiedUser, db: DB) -> list[Photo]:
    """The uploader's own photos with their moderation status (images only once published)."""
    return list(
        db.scalars(
            select(Photo)
            .where(
                Photo.event_id == event.id,
                Photo.uploaded_by == user.id,
                Photo.source == PhotoSource.guest,
                Photo.status != PhotoStatus.removed,
                # Hide uploads whose file never arrived (tab closed mid-upload, etc.);
                # the cleanup job deletes them once the upload URL has expired.
                ~((Photo.index_status == IndexStatus.queued) & Photo.original_key.is_(None)),
            )
            .order_by(Photo.created_at.desc())
            .limit(500)
        )
    )
