import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import OrderKind, OrderStatus, SubscriptionStatus
from app.services.billing.plans import PlanKey


class PlanOut(BaseModel):
    key: PlanKey
    name: str
    kind: Literal["one_off", "subscription"]
    price_cents: int
    max_attendees: int
    max_photos: int
    events_per_period: int


class PriceListOut(BaseModel):
    currency: str
    vat_rate: int
    vat_included: bool = True
    example_prices: bool  # placeholders until the operator sets real prices
    test_mode: bool  # no real payments (fake provider)
    plans: list[PlanOut]


class CheckoutIn(BaseModel):
    plan: PlanKey
    event_name: str | None = Field(default=None, min_length=1, max_length=200)
    event_date: dt.date | None = None


class CheckoutOut(BaseModel):
    order_id: uuid.UUID
    checkout_url: str


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan: str
    plan_name: str = ""
    kind: OrderKind
    amount_cents: int
    vat_cents: int = 0
    currency: str
    vat_rate: int
    status: OrderStatus
    failure_code: str | None
    event_name: str | None
    event_date: dt.date | None
    event_id: uuid.UUID | None
    created_at: dt.datetime
    paid_at: dt.datetime | None


class TestCheckoutOut(BaseModel):
    """The fake provider's hosted checkout page (TEST MODE)."""

    order: OrderOut
    test_cards: list[str]


class TestPaymentIn(BaseModel):
    # Only published test numbers are accepted; never stored or logged.
    card_number: str = Field(min_length=12, max_length=23, pattern=r"^[0-9 ]+$")
    expiry: str = Field(min_length=4, max_length=7)
    cvc: str = Field(min_length=3, max_length=4, pattern=r"^[0-9]+$")


Outcome = Literal["paid", "failed", "duplicate", "ignored"]


class TestPaymentOut(BaseModel):
    outcome: Outcome
    order: OrderOut


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan: str
    plan_name: str = ""
    status: SubscriptionStatus
    current_period_start: dt.datetime
    current_period_end: dt.datetime
    canceled_at: dt.datetime | None
    events_included: int = 0
    events_used: int = 0


class BillingOverviewOut(BaseModel):
    subscription: SubscriptionOut | None
    orders: list[OrderOut]


class SubscriptionEventIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    date: dt.date | None = None


class CreatedEventOut(BaseModel):
    event_id: uuid.UUID


class EventUsageOut(BaseModel):
    plan: str | None
    plan_name: str | None
    max_attendees: int | None
    max_photos: int | None
    attendees: int
    photos: int


class WebhookOut(BaseModel):
    status: Outcome
