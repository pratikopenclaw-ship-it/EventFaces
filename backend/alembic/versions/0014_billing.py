"""billing: orders, subscriptions, processed webhook events; plan limits on events

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

order_kind = sa.Enum("one_off", "subscription", "allowance", name="order_kind")
order_status = sa.Enum("pending", "paid", "canceled", name="order_status")
subscription_status = sa.Enum("active", "expired", name="subscription_status")
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("status", subscription_status, nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

    # Existing events have no plan: no limits (they were created by a super admin).
    op.add_column("events", sa.Column("plan", sa.String(20)))
    op.add_column("events", sa.Column("max_attendees", sa.Integer()))
    op.add_column("events", sa.Column("max_photos", sa.Integer()))
    op.add_column("events", sa.Column("subscription_id", UUID, sa.ForeignKey("subscriptions.id", ondelete="SET NULL")))
    op.create_index("ix_events_subscription_id", "events", ["subscription_id"])
    op.add_column("drive_sync_runs", sa.Column("files_over_limit", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("drive_sync_runs", "files_over_limit", server_default=None)

    op.create_table(
        "orders",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("kind", order_kind, nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("vat_rate", sa.Integer(), nullable=False),
        sa.Column("status", order_status, nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_ref", sa.String(100), unique=True),
        sa.Column("failure_code", sa.String(40)),
        sa.Column("event_name", sa.String(200)),
        sa.Column("event_date", sa.Date()),
        sa.Column("event_id", UUID, sa.ForeignKey("events.id", ondelete="SET NULL")),
        sa.Column("subscription_id", UUID, sa.ForeignKey("subscriptions.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_cents >= 0", name="ck_orders_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_orders_currency"),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])

    op.create_table(
        "webhook_events",
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("provider_event_id", sa.String(100), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_table("orders")
    op.drop_column("drive_sync_runs", "files_over_limit")
    op.drop_index("ix_events_subscription_id", table_name="events")
    for column in ("subscription_id", "max_photos", "max_attendees", "plan"):
        op.drop_column("events", column)
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    for enum in (order_kind, order_status, subscription_status):
        enum.drop(op.get_bind(), checkfirst=True)
