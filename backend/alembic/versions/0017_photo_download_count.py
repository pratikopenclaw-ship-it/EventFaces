"""photos.download_count: a plain aggregate for the organizer-facing engagement ranking

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "photos", sa.Column("download_count", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("photos", "download_count")
