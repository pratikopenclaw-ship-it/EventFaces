"""search grants, search audit log, face-search consent

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = lambda: sa.DateTime(timezone=True)

    op.add_column("users", sa.Column("face_consent_at", ts()))
    op.add_column("users", sa.Column("face_consent_version", sa.String(40)))

    op.create_table(
        "search_grants",
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "photo_id", pg.UUID(as_uuid=True), sa.ForeignKey("photos.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "event_id", pg.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", ts(), nullable=False),
    )
    op.create_index("ix_search_grants_photo_id", "search_grants", ["photo_id"])
    op.create_index("ix_search_grants_event_id", "search_grants", ["event_id"])

    op.create_table(
        "search_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("event_id", pg.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL")),
        sa.Column("match_count", sa.Integer(), nullable=False),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_search_audit_user_id", "search_audit", ["user_id"])
    op.create_index("ix_search_audit_event_id", "search_audit", ["event_id"])


def downgrade() -> None:
    op.drop_table("search_audit")
    op.drop_table("search_grants")
    op.drop_column("users", "face_consent_version")
    op.drop_column("users", "face_consent_at")
