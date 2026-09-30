import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import FeedbackVerdict


class SearchGrant(Base):
    """'User X matched photo Y': authorizes viewing/downloading Y. Contains no biometric
    data (no selfie, no embedding) and expires."""

    __tablename__ = "search_grants"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photos.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    # Which face matched and in which search: lets feedback be recorded from server-side
    # facts instead of client-supplied values. Lives only as long as the grant.
    face_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faces.id", ondelete="SET NULL")
    )
    search_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("search_audit.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SearchAudit(Base):
    """Audit log of searches: who, which event, when, how many matches. Never the selfie."""

    __tablename__ = "search_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    match_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )


class MatchFeedback(Base):
    """'This is me' / 'Not me' / 'Photos of me are missing'. Never a selfie or embedding.

    user/face/photo/search links are nulled (anonymized) when the event's face data
    expires, when the user withdraws consent or deletes their account; verdict +
    similarity + event stay for threshold statistics.
    """

    __tablename__ = "match_feedback"
    # One verdict per user per photo (migration 0006); partial, because anonymized rows
    # have user_id/photo_id nulled.
    __table_args__ = (
        Index(
            "uq_match_feedback_user_photo",
            "user_id",
            "photo_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL AND photo_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("search_audit.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("photos.id", ondelete="SET NULL"))
    face_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("faces.id", ondelete="SET NULL"))
    similarity_score: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[FeedbackVerdict] = mapped_column(Enum(FeedbackVerdict, name="feedback_verdict"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SelfieQuality(Base):
    """Quality metrics of one selfie shot (passed or rejected). No image, embedding or user."""

    __tablename__ = "selfie_quality"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    search_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("search_audit.id", ondelete="SET NULL"))
    shot: Mapped[str] = mapped_column(String(10), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(40))
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    face_count: Mapped[int] = mapped_column(Integer, nullable=False)
    det_score: Mapped[float | None] = mapped_column(Float)
    face_height_ratio: Mapped[float | None] = mapped_column(Float)
    yaw: Mapped[float | None] = mapped_column(Float)
    pitch: Mapped[float | None] = mapped_column(Float)
    roll: Mapped[float | None] = mapped_column(Float)
    blur: Mapped[float | None] = mapped_column(Float)
    brightness: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
