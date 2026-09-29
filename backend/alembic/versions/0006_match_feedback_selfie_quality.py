"""match feedback, selfie quality metrics, grant provenance

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

verdict = pg.ENUM("me", "not_me", "missing", name="feedback_verdict", create_type=False)


def upgrade() -> None:
    verdict.create(op.get_bind(), checkfirst=True)
    ts = lambda: sa.DateTime(timezone=True)  # noqa: E731
    uid = lambda: pg.UUID(as_uuid=True)  # noqa: E731

    op.add_column("search_grants", sa.Column("face_id", uid(), sa.ForeignKey("faces.id", ondelete="SET NULL")))
    op.add_column("search_grants", sa.Column("search_id", sa.BigInteger(), sa.ForeignKey("search_audit.id", ondelete="SET NULL")))

    op.create_table(
        "match_feedback",
        sa.Column("id", uid(), primary_key=True),
        sa.Column("search_id", sa.BigInteger(), sa.ForeignKey("search_audit.id", ondelete="SET NULL")),
        sa.Column("user_id", uid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("event_id", uid(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("photo_id", uid(), sa.ForeignKey("photos.id", ondelete="SET NULL")),
        sa.Column("face_id", uid(), sa.ForeignKey("faces.id", ondelete="SET NULL")),
        sa.Column("similarity_score", sa.Float()),
        sa.Column("verdict", verdict, nullable=False),
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_match_feedback_event_id", "match_feedback", ["event_id"])
    # One verdict per user per photo (updated if they change their mind).
    op.create_index(
        "uq_match_feedback_user_photo",
        "match_feedback",
        ["user_id", "photo_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL AND photo_id IS NOT NULL"),
    )

    op.create_table(
        "selfie_quality",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", uid(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("search_id", sa.BigInteger(), sa.ForeignKey("search_audit.id", ondelete="SET NULL")),
        sa.Column("shot", sa.String(10), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(40)),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("face_count", sa.Integer(), nullable=False),
        *[sa.Column(c, sa.Float()) for c in ("det_score", "face_height_ratio", "yaw", "pitch", "roll", "blur", "brightness")],
        sa.Column("created_at", ts(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_selfie_quality_event_id", "selfie_quality", ["event_id"])
    op.create_index("ix_selfie_quality_created_at", "selfie_quality", ["created_at"])


def downgrade() -> None:
    op.drop_table("selfie_quality")
    op.drop_table("match_feedback")
    op.drop_column("search_grants", "search_id")
    op.drop_column("search_grants", "face_id")
    verdict.drop(op.get_bind(), checkfirst=True)
