"""photo_shortlists: an attendee's personal picks within an event

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "photo_shortlists",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("photo_id", UUID, sa.ForeignKey("photos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", UUID, sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "photo_id", name="uq_photo_shortlists_user_photo"),
    )
    op.create_index("ix_photo_shortlists_user_id", "photo_shortlists", ["user_id"])
    op.create_index("ix_photo_shortlists_photo_id", "photo_shortlists", ["photo_id"])
    op.create_index("ix_photo_shortlists_event_id", "photo_shortlists", ["event_id"])


def downgrade() -> None:
    op.drop_table("photo_shortlists")
