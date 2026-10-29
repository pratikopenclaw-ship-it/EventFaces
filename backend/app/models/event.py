import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import JoinMode, MemberRole, MemberStatus, ModerationMode


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (CheckConstraint("accent_color ~ '^#[0-9a-f]{6}$'", name="ck_events_accent_color"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # nullable spelled out: the attribute name `date` shadows the type in its own
    # annotation, so SQLAlchemy can't see the Optional and would infer NOT NULL.
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
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
    # When a photo is indexed with zero detected faces: publish it straight away (default,
    # matches prior behaviour) or hold it as `pending_review` for an organizer to approve
    # via the moderation queue, same as under `moderation_mode.manual`.
    auto_publish_faceless_photos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Organizer switch: tell attendees who searched when new photos go live (photo_alerts).
    notify_new_photos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    allow_selfie_file_upload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delete_photos_on_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    drive_folder_id: Mapped[str | None] = mapped_column(String(200))
    # Organizer-chosen brand colour (#rrggbb, lowercase); the frontend derives readable
    # per-theme variants from it. NULL = the app's default accent.
    accent_color: Mapped[str | None] = mapped_column(String(7))
    # Storage key of the organizer's logo (re-encoded PNG), or NULL.
    logo_key: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retention_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Paid plan (services/billing/plans.py) and its limits. NULL = no limit (events created
    # by a super admin). Enforced on joining, invite acceptance, guest uploads and Drive import.
    plan: Mapped[str | None] = mapped_column(String(20))
    max_attendees: Mapped[int | None] = mapped_column(Integer)
    max_photos: Mapped[int | None] = mapped_column(Integer)
    # Set when the event came out of a subscription's monthly allowance.
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )

    @property
    def has_logo(self) -> bool:
        return self.logo_key is not None

    @property
    def upload_max_bytes(self) -> int:
        """Guest upload size limit (shown before choosing photos; enforced on upload)."""
        from app.core.config import get_settings

        return get_settings().guest_upload_max_bytes


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
