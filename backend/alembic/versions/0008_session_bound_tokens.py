"""bind refresh tokens (and so access tokens) to a login session

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("auth_tokens", sa.Column("session_id", pg.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_auth_tokens_session_id", "auth_tokens", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_session_id", table_name="auth_tokens")
    op.drop_column("auth_tokens", "session_id")
