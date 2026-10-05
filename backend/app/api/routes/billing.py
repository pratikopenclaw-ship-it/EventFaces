"""Pricing, checkout, payment confirmations (webhooks), orders and subscriptions.

Only a verified provider confirmation marks an order paid. With the fake provider
(TEST MODE), its hosted checkout is the two `test-checkout` endpoints: they accept only
published test card numbers and hand the provider's signed confirmation to the same code
path as the webhook.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.api.deps import DB, ManagedEvent, VerifiedUser
from app.core import rate_limit
from app.core.config import get_settings
from app.models import Order, OrderStatus, Subscription, User
from app.schemas.billing import (
    BillingOverviewOut,
    CheckoutIn,
    CheckoutOut,
    CreatedEventOut,
    EventUsageOut,
    OrderOut,
    PlanOut,
    PriceListOut,
    SubscriptionEventIn,
    SubscriptionOut,
    TestCheckoutOut,
    TestPaymentIn,
    TestPaymentOut,
    WebhookOut,
)
from app.services.billing import limits, orders
from app.services.billing.plans import CURRENCY, EXAMPLE_PRICES, PLANS, VAT_RATE, vat_part
from app.services.billing.provider import TEST_CARDS, InvalidConfirmation, get_provider

router = APIRouter(prefix="/api", tags=["billing"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
MAX_WEBHOOK_BYTES = 65_536


def order_out(order: Order) -> OrderOut:
    out = OrderOut.model_validate(order)
    plan = PLANS.get(order.plan)
    return out.model_copy(update={"plan_name": plan.name if plan else order.plan, "vat_cents": vat_part(order.amount_cents, order.vat_rate)})


def _own_order(db: DB, user: User, *, order_id: uuid.UUID | None = None, session_ref: str | None = None, lock: bool = False) -> Order:
    query = select(Order).where(Order.user_id == user.id)
    query = query.where(Order.id == order_id) if order_id else query.where(Order.provider_ref == session_ref)
    order = db.scalar(query.with_for_update() if lock else query)
    if order is None:  # also someone else's order: no difference visible
        raise NOT_FOUND
    return order


@router.get("/billing/plans", response_model=PriceListOut)
def price_list() -> PriceListOut:
    return PriceListOut(
        currency=CURRENCY,
        vat_rate=VAT_RATE,
        example_prices=EXAMPLE_PRICES,
        test_mode=get_provider().test_mode,
        plans=[PlanOut(**{k: getattr(p, k) for k in PlanOut.model_fields}) for p in PLANS.values()],
    )


@router.post("/billing/checkout", response_model=CheckoutOut)
def start_checkout(body: CheckoutIn, user: VerifiedUser, db: DB) -> CheckoutOut:
    rate_limit.enforce(f"checkout:{user.id}", rate_limit.Limit.parse(get_settings().checkout_rate_limit))
    order, url = orders.start_checkout(db, user, body.plan, body.event_name, body.event_date)
    return CheckoutOut(order_id=order.id, checkout_url=url)


@router.get("/billing/test-checkout/{session_ref}", response_model=TestCheckoutOut)
def test_checkout(session_ref: str, user: VerifiedUser, db: DB) -> TestCheckoutOut:
    if not get_provider().test_mode:
        raise NOT_FOUND
    return TestCheckoutOut(order=order_out(_own_order(db, user, session_ref=session_ref)), test_cards=list(TEST_CARDS))


@router.post("/billing/test-checkout/{session_ref}/pay", response_model=TestPaymentOut)
def test_pay(session_ref: str, body: TestPaymentIn, user: VerifiedUser, db: DB) -> TestPaymentOut:
    """The fake provider charging a test card, then confirming like a webhook would."""
    provider = get_provider()
    if not provider.test_mode:
        raise NOT_FOUND
    rate_limit.enforce(f"pay:{user.id}", rate_limit.Limit.parse(get_settings().payment_attempt_rate_limit))
    order = _own_order(db, user, session_ref=session_ref)
    if order.status != OrderStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This checkout is already closed")
    try:
        raw, headers = provider.confirmation_for(order, body.card_number)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This is a test checkout: use one of the test card numbers shown. No real card can be charged here.",
        ) from None
    db.rollback()  # release the snapshot; the confirmation locks the order itself
    result = orders.apply_confirmation(db, provider.name, provider.parse_confirmation(raw, headers))
    return TestPaymentOut(outcome=result.outcome, order=order_out(_own_order(db, user, session_ref=session_ref)))


WEBHOOK_OPENAPI: dict[str, object] = {
    "requestBody": {
        "required": True,
        "description": "The provider's signed event (JSON). Verified against the raw bytes.",
        "content": {"application/json": {"schema": {"type": "object"}}},
    },
    "parameters": [
        {"name": "Fake-Signature", "in": "header", "required": True, "schema": {"type": "string"}, "description": "t=<unix time>,v1=<HMAC-SHA256>"},
    ],
}


@router.post("/billing/webhook/fake", response_model=WebhookOut, openapi_extra=WEBHOOK_OPENAPI)
async def fake_webhook(request: Request, db: DB) -> WebhookOut:
    """Server-to-server payment confirmation. No session: authenticated only by its HMAC
    signature and timestamp (replays and forgeries are refused; each event applies once).
    Exempt from CSRF because it carries no cookies (api/csrf.py)."""
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"webhook:{ip}", rate_limit.Limit.parse(get_settings().webhook_rate_limit))
    raw = await _read_body(request)
    provider = get_provider()
    try:
        conf = provider.parse_confirmation(raw, dict(request.headers))
    except InvalidConfirmation:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature or payload") from None
    result = await run_in_threadpool(orders.apply_confirmation, db, provider.name, conf)
    return WebhookOut(status=result.outcome)


async def _read_body(request: Request) -> bytes:
    if int(request.headers.get("content-length") or 0) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Too large")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Too large")
    return body


@router.get("/billing/overview", response_model=BillingOverviewOut)
def overview(user: VerifiedUser, db: DB) -> BillingOverviewOut:
    rows = db.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(200)).all()
    sub = orders.active_subscription(db, user)
    return BillingOverviewOut(subscription=_subscription_out(db, sub) if sub else None, orders=[order_out(o) for o in rows])


@router.get("/billing/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, user: VerifiedUser, db: DB) -> OrderOut:
    return order_out(_own_order(db, user, order_id=order_id))


def _subscription_out(db: DB, sub: Subscription) -> SubscriptionOut:
    plan = PLANS[sub.plan]
    return SubscriptionOut.model_validate(sub).model_copy(
        update={"plan_name": plan.name, "events_included": plan.events_per_period, "events_used": orders.allowance_used(db, sub)}
    )


@router.post("/billing/subscription/cancel", response_model=SubscriptionOut)
def cancel_subscription(user: VerifiedUser, db: DB) -> SubscriptionOut:
    return _subscription_out(db, orders.cancel_subscription(db, user))


@router.post("/billing/subscription/events", response_model=CreatedEventOut)
def subscription_event(body: SubscriptionEventIn, user: VerifiedUser, db: DB) -> CreatedEventOut:
    rate_limit.enforce(f"checkout:{user.id}", rate_limit.Limit.parse(get_settings().checkout_rate_limit))
    return CreatedEventOut(event_id=orders.create_subscription_event(db, user, body.name, body.date).id)


@router.get("/events/{event_id}/usage", response_model=EventUsageOut)
def event_usage(event: ManagedEvent, db: DB) -> EventUsageOut:
    plan = PLANS.get(event.plan or "")
    return EventUsageOut(
        plan=event.plan,
        plan_name=plan.name if plan else None,
        max_attendees=event.max_attendees,
        max_photos=event.max_photos,
        attendees=limits.attendee_count(db, event),
        photos=limits.photo_count(db, event),
    )
