import uuid
from typing import Annotated, Literal

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select

from app.api.deps import DB, ManagedEvent, MemberEvent, VerifiedUser
from app.core import rate_limit, storage
from app.models import DriveSyncRun, Face, IndexStatus, Photo, PhotoStatus, SyncStatus, UserRole
from app.schemas.photo import PhotoAdminOut, PhotoPage, PipelineCounts, SyncRunOut, SyncStatusOut
from app.services import drive, watermark
from app.services.imaging import PREVIEW_QUALITY, THUMB_QUALITY
from app.services.photo_access import viewable_photo
from app.services.photo_pipeline import active_sync_run
from app.workers.tasks import sync_drive

router = APIRouter(prefix="/api", tags=["photos"])


class ServiceAccountOut(BaseModel):
    email: str | None


@router.get("/drive/service-account", response_model=ServiceAccountOut)
def drive_service_account(user: VerifiedUser) -> dict[str, str | None]:
    """The email organizers share their Drive folder with."""
    if user.role == UserRole.attendee:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    return {"email": drive.service_account_email()}


@router.post("/events/{event_id}/sync", response_model=SyncRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_sync(event: ManagedEvent, user: VerifiedUser, db: DB) -> DriveSyncRun:
    rate_limit.enforce(f"sync:{event.id}", rate_limit.Limit(20, 3600))
    if not event.drive_folder_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link a Google Drive folder first")
    if drive.service_account_email() is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google Drive import is not configured")
    if active_sync_run(db, event.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A sync is already running")

    run = DriveSyncRun(
        event_id=event.id, folder_id=event.drive_folder_id, status=SyncStatus.queued, started_by=user.id
    )
    db.add(run)
    db.commit()
    sync_drive.delay(str(run.id))
    db.refresh(run)
    return run


@router.get("/events/{event_id}/sync", response_model=SyncStatusOut)
def sync_status(event: ManagedEvent, db: DB) -> SyncStatusOut:
    last_run = db.scalar(
        select(DriveSyncRun)
        .where(DriveSyncRun.event_id == event.id)
        .order_by(DriveSyncRun.created_at.desc())
        .limit(1)
    )
    # Explicit comprehension: dict(Result) treats it as a mapping (it has .keys()) and fails.
    counts: dict[IndexStatus, int] = {
        index_status: n
        for index_status, n in db.execute(
            select(Photo.index_status, func.count())
            .where(Photo.event_id == event.id, Photo.status != PhotoStatus.removed)
            .group_by(Photo.index_status)
        ).tuples()
    }
    pipeline = PipelineCounts(**{s.value: counts.get(s, 0) for s in IndexStatus})
    published = db.scalar(
        select(func.count()).select_from(Photo).where(
            Photo.event_id == event.id, Photo.status == PhotoStatus.published
        )
    )
    faces = db.scalar(select(func.count()).select_from(Face).where(Face.event_id == event.id))
    in_progress = active_sync_run(db, event.id) is not None or any(
        (pipeline.queued, pipeline.importing, pipeline.indexing)
    )
    return SyncStatusOut(
        drive_configured=drive.service_account_email() is not None,
        service_account_email=drive.service_account_email(),
        folder_id=event.drive_folder_id,
        last_run=SyncRunOut.model_validate(last_run) if last_run else None,
        in_progress=in_progress,
        pipeline=pipeline,
        published_photos=published or 0,
        faces=faces or 0,
    )


@router.get("/events/{event_id}/photos", response_model=PhotoPage)
def list_photos(
    event: ManagedEvent,
    db: DB,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
    index_status: IndexStatus | None = None,
    photo_status: Annotated[PhotoStatus | None, Query(alias="status")] = None,
) -> PhotoPage:
    where = [Photo.event_id == event.id, Photo.status != PhotoStatus.removed]
    if index_status is not None:
        where.append(Photo.index_status == index_status)
    if photo_status is not None:
        where.append(Photo.status == photo_status)
    total = db.scalar(select(func.count()).select_from(Photo).where(*where)) or 0
    items = db.scalars(
        select(Photo).where(*where).order_by(Photo.created_at.desc(), Photo.id).offset(offset).limit(limit)
    ).all()
    return PhotoPage(items=[PhotoAdminOut.model_validate(p) for p in items], total=total)


@router.get("/events/{event_id}/photos/{photo_id}/{variant}")
def photo_image(
    photo_id: uuid.UUID, variant: Literal["thumb", "preview"], event: MemberEvent, user: VerifiedUser, db: DB
) -> Response:
    """Thumbnail/preview streamed from storage (storage URLs are never exposed).

    Organizers see every photo of their event; attendees only photos they matched or
    uploaded. `viewable_photo` also requires the photo to belong to *this* event, so an
    ID from another event can't be smuggled in via this event's URL.
    """
    photo = viewable_photo(db, event, user, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    key = photo.thumb_key if variant == "thumb" else photo.preview_key
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not ready yet")
    headers = {"Cache-Control": "private, max-age=300"}
    if event.logo_key is None:
        body, length = storage.open_stream(key)
        if length:
            headers["Content-Length"] = str(length)
        return StreamingResponse(body.iter_chunks(), media_type="image/jpeg", headers=headers)

    quality = THUMB_QUALITY if variant == "thumb" else PREVIEW_QUALITY
    data = watermark.maybe_apply(storage.get_bytes(key), event, storage.get_bytes(event.logo_key), quality)
    return Response(content=data, media_type="image/jpeg", headers=headers)
