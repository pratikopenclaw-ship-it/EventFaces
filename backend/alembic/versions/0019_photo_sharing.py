"""photos.shared_at / shared_by: organizer-shared photos with no detected face

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("photos", sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "photos",
        sa.Column(
            "shared_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="photos_shared_by_fkey"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("photos", "shared_by")
    op.drop_column("photos", "shared_at")
