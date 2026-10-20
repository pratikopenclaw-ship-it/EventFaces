import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.models.enums import IndexStatus, PhotoSource, PhotoStatus, SyncStatus


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: SyncStatus
    folder_id: str
    files_listed: int
    files_new: int
    files_retried: int
    files_over_limit: int = 0  # not imported: the plan's photo limit
    error: str | None
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None


class PipelineCounts(BaseModel):
    queued: int = 0
    importing: int = 0
    indexing: int = 0
    indexed: int = 0
    failed: int = 0


class SyncStatusOut(BaseModel):
    drive_configured: bool
    service_account_email: str | None
    folder_id: str | None
    last_run: SyncRunOut | None
    in_progress: bool
    pipeline: PipelineCounts
    published_photos: int
    faces: int


class PhotoAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: PhotoSource
    status: PhotoStatus
    index_status: IndexStatus
    original_filename: str | None
    width: int | None
    height: int | None
    face_count: int
    download_count: int
    error: str | None
    created_at: dt.datetime
    shared_at: dt.datetime | None = None


class PhotoPage(BaseModel):
    items: list[PhotoAdminOut]
    total: int


class SharePhotosIn(BaseModel):
    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    shared: StrictBool


class ShareFacelessIn(BaseModel):
    # The organizer confirms they looked: "no face detected" doesn't mean "no people".
    confirm_no_people: StrictBool


class ShareResultOut(BaseModel):
    changed: int
    skipped: int


class SharedPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    width: int | None
    height: int | None
