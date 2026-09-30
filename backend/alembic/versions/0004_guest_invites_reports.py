"""guest uploads, invites, photo reports

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

invite_status = pg.ENUM("pending", "accepted", "revoked", name="invite_status", create_type=False)
report_status = pg.ENUM("open", "dismissed", "photo_removed", name="report_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    invite_status.create(bind, checkfirst=True)
    report_status.create(bind, checkfirst=True)
    ts = lambda: sa.DateTime(timezone=True)
    fk = lambda t, d: sa.ForeignKey(f"{t}.id", ondelete=d)

    op.add_column("photos", sa.Column("upload_key", sa.String(300)))
    op.add_column("photos", sa.Column("upload_content_type", sa.String(40)))

    op.create_table(
        "invites",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", pg.UUID(as_uuid=True), fk("events", "CASCADE"), nullable=False),
        sa.Column("email", pg.CITEXT(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", invite_status, nullable=False),
        sa.Column("invited_by", pg.UUID(as_uuid=True), fk("users", "SET NULL")),
        sa.Column("accepted_by", pg.UUID(as_uuid=True), fk("users", "SET NULL")),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", ts()),
        sa.Column("expires_at", ts(), nullable=False),
        sa.Column("accepted_at", ts()),
        sa.UniqueConstraint("event_id", "email", name="uq_invites_event_email"),
    )
    op.create_index("ix_invites_event_id", "invites", ["event_id"])

    op.create_table(
        "photo_reports",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("photo_id", pg.UUID(as_uuid=True), fk("photos", "CASCADE"), nullable=False),
        sa.Column("event_id", pg.UUID(as_uuid=True), fk("events", "CASCADE"), nullable=False),
        sa.Column("reporter_id", pg.UUID(as_uuid=True), fk("users", "SET NULL")),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", report_status, nullable=False),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", ts()),
        sa.Column("resolved_by", pg.UUID(as_uuid=True), fk("users", "SET NULL")),
    )
    op.create_index("ix_photo_reports_photo_id", "photo_reports", ["photo_id"])
    op.create_index("ix_photo_reports_event_id", "photo_reports", ["event_id"])


def downgrade() -> None:
    op.drop_table("photo_reports")
    op.drop_table("invites")
    op.drop_column("photos", "upload_content_type")
    op.drop_column("photos", "upload_key")
    bind = op.get_bind()
    report_status.drop(bind, checkfirst=True)
    invite_status.drop(bind, checkfirst=True)
