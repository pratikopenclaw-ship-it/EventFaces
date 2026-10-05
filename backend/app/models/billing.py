"""Orders and subscriptions (services/billing). Business records: kept when an account is
deleted (the user link becomes NULL), because invoices must be retained; they hold no
personal data of their own (no names, emails or card details)."""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import OrderKind, OrderStatus, SubscriptionStatus


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"), nullable=False, default=SubscriptionStatus.active
    )
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Canceled by the customer: stays active until current_period_end, then expires.
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_orders_amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_orders_currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[OrderKind] = mapped_column(Enum(OrderKind, name="order_kind"), nullable=False)
    # Gross amount (incl. VAT) in the currency's minor unit; the VAT rate applied, in percent.
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"), nullable=False, default=OrderStatus.pending
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    # The provider's checkout session id (fake: random; Stripe: cs_...). Unique per order.
    provider_ref: Mapped[str | None] = mapped_column(String(100), unique=True)
    # Why the last payment attempt failed (e.g. card_declined); the order stays payable.
    failure_code: Mapped[str | None] = mapped_column(String(40))
    # The event the customer asked for (created on payment).
    event_name: Mapped[str | None] = mapped_column(String(200))
    event_date: Mapped[date | None] = mapped_column(Date)
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL")
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEvent(Base):
    """Provider events already processed: a replayed confirmation is a no-op."""

    __tablename__ = "webhook_events"

    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    provider_event_id: Mapped[str] = mapped_column(String(100), primary_key=True)  # e.g. evt_...
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
