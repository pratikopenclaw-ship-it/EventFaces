"""removal requests

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

removal_status = pg.ENUM("unverified", "submitted", "resolved", "declined", name="removal_status", create_type=False)


def upgrade() -> None:
    removal_status.create(op.get_bind(), checkfirst=True)
    ts = lambda: sa.DateTime(timezone=True)
    op.create_table(
        "removal_requests",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", pg.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", pg.CITEXT(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", removal_status, nullable=False),
        sa.Column("matched_photo_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("verified_at", ts()),
        sa.Column("resolved_at", ts()),
        sa.Column("resolved_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index("ix_removal_requests_event_id", "removal_requests", ["event_id"])
    # Retention job scans these.
    op.create_index("ix_search_audit_created_at", "search_audit", ["created_at"])
    op.create_index("ix_search_grants_expires_at", "search_grants", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_search_grants_expires_at", "search_grants")
    op.drop_index("ix_search_audit_created_at", "search_audit")
    op.drop_table("removal_requests")
    removal_status.drop(op.get_bind(), checkfirst=True)
