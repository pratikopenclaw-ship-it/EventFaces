"""New-photo alerts (services/photo_alerts.py). Not biometric, but a row records that a
user searched an event, so it is personal data: deleted with the event's face data, on
consent withdrawal and with the account, and never shown to organizers or admins."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EventPhotoAlert(Base):
    """One per (user, event), created by the user's first search of the event."""

    __tablename__ = "event_photo_alerts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    last_searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Newest published_at already covered by a notice; photos up to it never alert again.
    notified_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertToken(Base):
    """Unsubscribe link token (email), bound to user + event. Stored only as its SHA-256
    hash (services/tokens.py); reusable until it expires, so "this event" then "all" works."""

    __tablename__ = "alert_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
