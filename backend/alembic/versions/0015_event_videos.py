"""event_videos: organizer-added video links shown on the event page's Videos tab

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "event_videos",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("event_id", UUID, sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_event_videos_event_id", "event_videos", ["event_id"])


def downgrade() -> None:
    op.drop_table("event_videos")
