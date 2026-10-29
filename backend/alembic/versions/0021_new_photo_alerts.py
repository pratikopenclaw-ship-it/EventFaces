"""New-photo alerts: photos.published_at, opt-out switches, event_photo_alerts, alert_tokens

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("photos", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    # Photos already live: the best known time they went live. No alerts follow from this,
    # because alerts only go to people whose search happened after the release.
    op.execute("UPDATE photos SET published_at = coalesce(indexed_at, created_at) WHERE status = 'published'")
    op.create_index("ix_photos_event_published", "photos", ["event_id", "published_at"])
    op.add_column("users", sa.Column("new_photo_alerts", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("events", sa.Column("notify_new_photos", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "event_photo_alerts",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_searched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notified_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_event_photo_alerts_event_id", "event_photo_alerts", ["event_id"])

    op.create_table(
        "alert_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_tokens_user_id", "alert_tokens", ["user_id"])
    op.create_index("ix_alert_tokens_event_id", "alert_tokens", ["event_id"])


def downgrade() -> None:
    op.drop_table("alert_tokens")
    op.drop_table("event_photo_alerts")
    op.drop_column("events", "notify_new_photos")
    op.drop_column("users", "new_photo_alerts")
    op.drop_index("ix_photos_event_published", table_name="photos")
    op.drop_column("photos", "published_at")
