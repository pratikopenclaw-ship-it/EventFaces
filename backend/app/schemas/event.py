import datetime as dt
import uuid
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import JoinMode, MemberRole, MemberStatus, ModerationMode
from app.services.drive_ids import parse_drive_folder_id


def _drive_folder(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    if len(v) > 500:
        raise ValueError("Drive folder value too long")
    folder_id = parse_drive_folder_id(v)
    if folder_id is None:
        raise ValueError("Not a valid Google Drive folder URL or ID")
    return folder_id


def _accent(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip().lower()
    if len(v) != 7 or v[0] != "#" or any(c not in "0123456789abcdef" for c in v[1:]):
        raise ValueError("Accent colour must look like #1a7f74")
    return v


# "#rrggbb" (any case, normalized to lowercase); blank clears it.
AccentColor = Annotated[str | None, AfterValidator(_accent)]

# Accepts a Drive folder URL or bare ID; normalized to the ID.
DriveFolder = Annotated[str | None, AfterValidator(_drive_folder)]

# Client timestamps must carry a timezone (a bare "10:00" is ambiguous and can't be
# compared with the server's aware clock); stored and returned in UTC.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda v: v.astimezone(dt.UTC))]


class EventBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    date: dt.date | None = None
    description: str = Field(default="", max_length=5000)
    join_mode: JoinMode = JoinMode.code
    access_expires_at: UtcDatetime | None = None
    guest_upload_enabled: bool = False
    moderation_mode: ModerationMode = ModerationMode.manual
    allow_selfie_file_upload: bool = False
    delete_photos_on_expiry: bool = False
    drive_folder: DriveFolder = None
    accent_color: AccentColor = None


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    """All fields optional; only provided fields are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    date: dt.date | None = None
    description: str | None = Field(default=None, max_length=5000)
    join_mode: JoinMode | None = None
    access_expires_at: UtcDatetime | None = None
    guest_upload_enabled: bool | None = None
    moderation_mode: ModerationMode | None = None
    allow_selfie_file_upload: bool | None = None
    delete_photos_on_expiry: bool | None = None
    drive_folder: DriveFolder = None
    accent_color: AccentColor = None


class EventPublicOut(BaseModel):
    """What attendees see: no access code, no admin settings."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    date: dt.date | None
    description: str
    access_expires_at: dt.datetime | None
    guest_upload_enabled: bool
    allow_selfie_file_upload: bool
    accent_color: str | None = None
    has_logo: bool = False
    upload_max_bytes: int | None = None


class EventAdminOut(EventPublicOut):
    join_mode: JoinMode
    access_code: str
    moderation_mode: ModerationMode
    delete_photos_on_expiry: bool
    drive_folder_id: str | None
    created_at: dt.datetime


class EventListItem(EventPublicOut):
    my_role: MemberRole | None = None
    can_manage: bool = False
    photo_count: int = 0
    # The caller's queued ("we'll notify you") search for this event, if any.
    search_state: str | None = None


class JoinPreviewOut(BaseModel):
    slug: str
    name: str
    date: dt.date | None
    join_mode: JoinMode
    # The event's colour, so the join page already looks like the event (no logo: that
    # needs membership).
    accent_color: str | None = None


class JoinIn(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=32)


class CodeOnlyJoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    role: MemberRole
    status: MemberStatus
    joined_at: dt.datetime
    expires_at: dt.datetime | None


class MemberUpdate(BaseModel):
    status: MemberStatus | None = None
    expires_at: UtcDatetime | None = None


class OrganizerAssign(BaseModel):
    email: EmailStr


class EventVideoIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=500)


class EventVideoOut(BaseModel):
    id: uuid.UUID
    title: str
    url: str
    provider: str
    embed_url: str
    created_at: dt.datetime
