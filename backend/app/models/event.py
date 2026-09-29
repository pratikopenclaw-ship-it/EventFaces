import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import JoinMode, MemberRole, MemberStatus, ModerationMode


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    join_mode: Mapped[JoinMode] = mapped_column(
        Enum(JoinMode, name="join_mode"), nullable=False, default=JoinMode.code
    )
    access_code: Mapped[str] = mapped_column(String(32), nullable=False)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    guest_upload_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    moderation_mode: Mapped[ModerationMode] = mapped_column(
        Enum(ModerationMode, name="moderation_mode"), nullable=False, default=ModerationMode.manual
    )
    allow_selfie_file_upload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delete_photos_on_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    drive_folder_id: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retention_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventMember(Base):
    __tablename__ = "event_members"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, name="member_role"), nullable=False, default=MemberRole.attendee
    )
    status: Mapped[MemberStatus] = mapped_column(
        Enum(MemberStatus, name="member_status"), nullable=False, default=MemberStatus.pending
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
