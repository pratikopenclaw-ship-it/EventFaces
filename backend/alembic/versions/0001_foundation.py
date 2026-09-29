"""foundation: users, auth tokens, events, memberships

Revision ID: 0001
Revises:
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = pg.ENUM("super_admin", "organizer", "attendee", name="user_role", create_type=False)
token_kind = pg.ENUM(
    "verify_email", "reset_password", "refresh", "invite", name="token_kind", create_type=False
)
join_mode = pg.ENUM("code", "invite", name="join_mode", create_type=False)
moderation_mode = pg.ENUM("auto", "manual", name="moderation_mode", create_type=False)
member_role = pg.ENUM("organizer", "attendee", name="member_role", create_type=False)
member_status = pg.ENUM("pending", "approved", "revoked", name="member_status", create_type=False)
ENUMS = [user_role, token_kind, join_mode, moderation_mode, member_role, member_status]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    for enum in ENUMS:
        enum.create(bind, checkfirst=True)

    ts = lambda: sa.DateTime(timezone=True)  # noqa: E731

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", pg.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("email_verified_at", ts()),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", ts()),
    )

    op.create_table(
        "auth_tokens",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", token_kind, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", ts(), nullable=False),
        sa.Column("used_at", ts()),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])

    op.create_table(
        "events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("date", sa.Date()),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("join_mode", join_mode, nullable=False),
        sa.Column("access_code", sa.String(32), nullable=False),
        sa.Column("access_expires_at", ts()),
        sa.Column("guest_upload_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("moderation_mode", moderation_mode, nullable=False),
        sa.Column(
            "allow_selfie_file_upload", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "delete_photos_on_expiry", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("drive_folder_id", sa.String(200)),
        sa.Column(
            "created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("retention_completed_at", ts()),
    )

    op.create_table(
        "event_members",
        sa.Column(
            "event_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", member_role, nullable=False),
        sa.Column("status", member_status, nullable=False),
        sa.Column("joined_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", ts()),
    )
    op.create_index("ix_event_members_user_id", "event_members", ["user_id"])


def downgrade() -> None:
    op.drop_table("event_members")
    op.drop_table("events")
    op.drop_table("auth_tokens")
    op.drop_table("users")
    bind = op.get_bind()
    for enum in reversed(ENUMS):
        enum.drop(bind, checkfirst=True)
