"""App Attest results on devices (report-only)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("attest_key_id", sa.String(44)))
    op.add_column("devices", sa.Column("attest_public_key", sa.String(128)))
    op.add_column("devices", sa.Column("attest_counter", sa.BigInteger()))
    op.add_column("devices", sa.Column("attest_status", sa.String(16)))
    op.add_column("devices", sa.Column("attest_reason", sa.String(40)))
    op.add_column("devices", sa.Column("attest_checked_at", sa.DateTime(timezone=True)))
    op.add_column("devices", sa.Column("assertion_status", sa.String(16)))
    op.add_column("devices", sa.Column("assertion_reason", sa.String(40)))
    op.create_unique_constraint("devices_attest_key_id_key", "devices", ["attest_key_id"])


def downgrade() -> None:
    op.drop_constraint("devices_attest_key_id_key", "devices", type_="unique")
    for column in (
        "assertion_reason",
        "assertion_status",
        "attest_checked_at",
        "attest_reason",
        "attest_status",
        "attest_counter",
        "attest_public_key",
        "attest_key_id",
    ):
        op.drop_column("devices", column)
