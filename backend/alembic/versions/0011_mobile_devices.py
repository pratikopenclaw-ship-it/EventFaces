"""mobile app: devices (device-bound sessions), passwordless accounts, event logos

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("app_version", sa.String(32), nullable=False),
        sa.Column("public_key", sa.String(128), nullable=False),
        sa.Column("apns_token", sa.String(200)),
        sa.Column("apns_env", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_devices_user_id", "devices", ["user_id"])
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=True)
    # Undo the downgrade's placeholder ('!' is never a valid Argon2 hash): no password.
    op.execute("UPDATE users SET password_hash = NULL WHERE password_hash = '!'")
    op.add_column("events", sa.Column("logo_key", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "logo_key")
    # Passwordless accounts can't log in on the old schema; give them an unusable hash.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=False)
    op.drop_index("ix_devices_user_id", table_name="devices")
    op.drop_table("devices")
