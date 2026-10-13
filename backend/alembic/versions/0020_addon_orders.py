"""addon_orders: per-photo add-on purchases (human editing, later ai_enhance/print)

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

addon_kind = sa.Enum("human_edit", name="addon_kind")
addon_order_status = sa.Enum("pending", "paid", "canceled", name="addon_order_status")
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "addon_orders",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("buyer_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("event_id", UUID, sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", addon_kind, nullable=False),
        sa.Column("photo_ids", postgresql.ARRAY(UUID), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("vat_rate", sa.Integer, nullable=False),
        sa.Column("status", addon_order_status, nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_ref", sa.String(100), unique=True),
        sa.Column("failure_code", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_cents >= 0", name="ck_addon_orders_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_addon_orders_currency"),
        sa.CheckConstraint("array_length(photo_ids, 1) > 0", name="ck_addon_orders_photo_ids_not_empty"),
    )
    op.create_index("ix_addon_orders_buyer_user_id", "addon_orders", ["buyer_user_id"])
    op.create_index("ix_addon_orders_event_id", "addon_orders", ["event_id"])


def downgrade() -> None:
    op.drop_table("addon_orders")
    addon_order_status.drop(op.get_bind(), checkfirst=True)
    addon_kind.drop(op.get_bind(), checkfirst=True)
