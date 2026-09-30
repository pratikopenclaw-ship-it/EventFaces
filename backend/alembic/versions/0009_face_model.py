"""record which face engine/model produced each embedding

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every face indexed so far came from the original engine.
    op.add_column(
        "faces",
        sa.Column("model", sa.String(64), nullable=False, server_default="insightface/buffalo_l"),
    )


def downgrade() -> None:
    op.drop_column("faces", "model")
