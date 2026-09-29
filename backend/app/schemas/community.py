import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import IndexStatus, InviteStatus, PhotoStatus, ReportStatus
from app.schemas.auth import Password


class UploadStartIn(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    content_type: str = Field(max_length=40)
    size: int = Field(gt=0)


class UploadStartOut(BaseModel):
    photo_id: uuid.UUID
    upload_url: str
    content_type: str
    expires_in: int


class MyUploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str | None
    status: PhotoStatus
    index_status: IndexStatus
    error: str | None
    created_at: dt.datetime


class ModerationItem(BaseModel):
    id: uuid.UUID
    original_filename: str | None
    uploader_email: str | None
    index_status: IndexStatus
    face_count: int
    created_at: dt.datetime


class ModerateIn(BaseModel):
    action: Literal["approve", "reject"]


ReportReason = Literal["inappropriate", "its_me_remove", "privacy", "other"]


class ReportIn(BaseModel):
    reason: ReportReason
    details: str = Field(default="", max_length=1000)


class ReportOut(BaseModel):
    id: uuid.UUID
    photo_id: uuid.UUID
    reason: str
    details: str
    status: ReportStatus
    reporter_email: str | None
    created_at: dt.datetime


class ResolveReportIn(BaseModel):
    action: Literal["dismiss", "remove_photo"]


class InviteCsvIn(BaseModel):
    csv: str = Field(min_length=3, max_length=500_000)


class InviteUploadOut(BaseModel):
    sent: list[str]
    invalid: list[str]
    already_members: list[str]
    already_accepted: list[str]


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    status: InviteStatus
    sent_at: dt.datetime | None
    expires_at: dt.datetime
    accepted_at: dt.datetime | None


class InvitePreview(BaseModel):
    event_name: str
    event_date: dt.date | None
    email: str
    account_exists: bool
    accepted: bool


class InviteTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class InviteRegisterIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Password
