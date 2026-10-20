import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import IndexStatus, PhotoSource, PhotoStatus, SyncStatus

EMBEDDING_DIM = 512
DEFAULT_FACE_MODEL = "insightface/buffalo_l"  # model of every face indexed before migration 0009


class Photo(Base):
    __tablename__ = "photos"
    __table_args__ = (UniqueConstraint("event_id", "drive_file_id", name="uq_photos_event_drive_file"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[PhotoSource] = mapped_column(Enum(PhotoSource, name="photo_source"), nullable=False)
    drive_file_id: Mapped[str | None] = mapped_column(String(200))
    original_filename: Mapped[str | None] = mapped_column(String(500))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[PhotoStatus] = mapped_column(
        Enum(PhotoStatus, name="photo_status"), nullable=False, default=PhotoStatus.processing
    )
    index_status: Mapped[IndexStatus] = mapped_column(
        Enum(IndexStatus, name="index_status"), nullable=False, default=IndexStatus.queued
    )
    error: Mapped[str | None] = mapped_column(Text)
    # Guest uploads land here first (presigned PUT), then get re-encoded and deleted.
    upload_key: Mapped[str | None] = mapped_column(String(300))
    upload_content_type: Mapped[str | None] = mapped_column(String(40))
    original_key: Mapped[str | None] = mapped_column(String(300))
    preview_key: Mapped[str | None] = mapped_column(String(300))
    thumb_key: Mapped[str | None] = mapped_column(String(300))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    face_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A plain aggregate (never tied to who downloaded): not personal data, so it isn't part
    # of the retention/anonymization paths that cover faces and grants.
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when an organizer shares a published photo with no detected face with every
    # member of the event (services/sharing.py). Cleared when faces are found or the photo
    # is retired; photo_access only honours it for face_count == 0.
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shared_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Face(Base):
    """One detected face. Embeddings are biometric data: deleted at event retention."""

    __tablename__ = "faces"
    # Declared so autogenerate never proposes dropping it (created in migration 0002).
    __table_args__ = (
        Index(
            "ix_faces_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized from photos so the vector search can filter by event without a join.
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bbox: Mapped[list[float]] = mapped_column(ARRAY(Float), nullable=False)  # x1, y1, x2, y2 (px)
    det_score: Mapped[float] = mapped_column(Float, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    # The engine/model that produced the embedding (FaceEngine.model_id). Embeddings from
    # different models aren't comparable: search only looks at the current model's faces.
    model: Mapped[str] = mapped_column(String(64), nullable=False, server_default=DEFAULT_FACE_MODEL)


class DriveSyncRun(Base):
    __tablename__ = "drive_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    folder_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"), nullable=False, default=SyncStatus.queued
    )
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    files_listed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_retried: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_over_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # skipped: plan's photo limit
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
