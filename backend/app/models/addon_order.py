"""Per-photo add-on purchases (human editing, and later AI enhancement, print+ship).
Separate from `models/billing.Order`, which is event-purchase-shaped: an add-on order
targets specific photos in an already-existing event, not a new event or subscription."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import AddonKind, AddonOrderStatus


class AddonOrder(Base):
    __tablename__ = "addon_orders"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_addon_orders_amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_addon_orders_currency"),
        CheckConstraint("array_length(photo_ids, 1) > 0", name="ck_addon_orders_photo_ids_not_empty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[AddonKind] = mapped_column(Enum(AddonKind, name="addon_kind"), nullable=False)
    photo_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AddonOrderStatus] = mapped_column(
        Enum(AddonOrderStatus, name="addon_order_status"), nullable=False, default=AddonOrderStatus.pending
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(100), unique=True)
    failure_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
