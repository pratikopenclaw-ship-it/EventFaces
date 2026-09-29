"""photos, faces (pgvector + HNSW), drive sync runs

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

photo_source = pg.ENUM("drive", "guest", name="photo_source", create_type=False)
photo_status = pg.ENUM(
    "processing", "published", "pending_review", "rejected", "removed", name="photo_status", create_type=False
)
index_status = pg.ENUM(
    "queued", "importing", "indexing", "indexed", "failed", name="index_status", create_type=False
)
sync_status = pg.ENUM("queued", "running", "completed", "failed", name="sync_status", create_type=False)
ENUMS = [photo_source, photo_status, index_status, sync_status]


def upgrade() -> None:
    bind = op.get_bind()
    for enum in ENUMS:
        enum.create(bind, checkfirst=True)

    ts = lambda: sa.DateTime(timezone=True)  # noqa: E731
    uuid_fk = lambda table, ondelete: sa.ForeignKey(f"{table}.id", ondelete=ondelete)  # noqa: E731

    op.create_table(
        "photos",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", pg.UUID(as_uuid=True), uuid_fk("events", "CASCADE"), nullable=False),
        sa.Column("source", photo_source, nullable=False),
        sa.Column("drive_file_id", sa.String(200)),
        sa.Column("original_filename", sa.String(500)),
        sa.Column("uploaded_by", pg.UUID(as_uuid=True), uuid_fk("users", "SET NULL")),
        sa.Column("status", photo_status, nullable=False),
        sa.Column("index_status", index_status, nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("original_key", sa.String(300)),
        sa.Column("preview_key", sa.String(300)),
        sa.Column("thumb_key", sa.String(300)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("face_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("indexed_at", ts()),
        sa.UniqueConstraint("event_id", "drive_file_id", name="uq_photos_event_drive_file"),
    )
    op.create_index("ix_photos_event_id", "photos", ["event_id"])

    op.create_table(
        "faces",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("photo_id", pg.UUID(as_uuid=True), uuid_fk("photos", "CASCADE"), nullable=False),
        sa.Column("event_id", pg.UUID(as_uuid=True), uuid_fk("events", "CASCADE"), nullable=False),
        sa.Column("bbox", pg.ARRAY(sa.Float()), nullable=False),
        sa.Column("det_score", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
    )
    op.create_index("ix_faces_photo_id", "faces", ["photo_id"])
    op.create_index("ix_faces_event_id", "faces", ["event_id"])
    # Approximate nearest-neighbour index for cosine distance (<=>). Searches always
    # filter by event_id; pgvector >= 0.8 iterative scans keep recall under that filter.
    op.execute(
        "CREATE INDEX ix_faces_embedding_hnsw ON faces USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "drive_sync_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", pg.UUID(as_uuid=True), uuid_fk("events", "CASCADE"), nullable=False),
        sa.Column("folder_id", sa.String(200), nullable=False),
        sa.Column("status", sync_status, nullable=False),
        sa.Column("started_by", pg.UUID(as_uuid=True), uuid_fk("users", "SET NULL")),
        sa.Column("files_listed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_retried", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", ts()),
        sa.Column("finished_at", ts()),
    )
    op.create_index("ix_drive_sync_runs_event_id", "drive_sync_runs", ["event_id"])


def downgrade() -> None:
    op.drop_table("drive_sync_runs")
    op.drop_table("faces")
    op.drop_table("photos")
    bind = op.get_bind()
    for enum in reversed(ENUMS):
        enum.drop(bind, checkfirst=True)
