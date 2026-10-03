"""user theme preference and per-event accent colour

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

theme = sa.Enum("system", "light", "dark", name="theme_preference")


def upgrade() -> None:
    theme.create(op.get_bind())
    op.add_column("users", sa.Column("theme", theme, nullable=False, server_default="system"))
    op.add_column("events", sa.Column("accent_color", sa.String(7), nullable=True))
    op.create_check_constraint("ck_events_accent_color", "events", "accent_color ~ '^#[0-9a-f]{6}$'")


def downgrade() -> None:
    op.drop_constraint("ck_events_accent_color", "events", type_="check")
    op.drop_column("events", "accent_color")
    op.drop_column("users", "theme")
    theme.drop(op.get_bind())
