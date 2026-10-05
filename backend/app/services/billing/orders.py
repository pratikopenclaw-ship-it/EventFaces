"""Orders, payment confirmations, fulfilment and subscriptions.

Flow: `start_checkout` (pending order + provider session) → the provider confirms server to
server → `apply_confirmation` (verified, idempotent) → `_fulfil`: the event is created, the
buyer becomes its organizer, and the Organizer Terms + DPA gate applies before managing it.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.db import affected
from app.core.security import utcnow
from app.models import (
    Event,
    EventMember,
    MemberRole,
    MemberStatus,
    Order,
    OrderKind,
    OrderStatus,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
    WebhookEvent,
)
from app.services.billing.plans import CURRENCY, PLANS, SUBSCRIPTION_PERIOD_DAYS, VAT_RATE, Plan
from app.services.billing.provider import Confirmation, get_provider
from app.services.events import new_event

log = logging.getLogger(__name__)

PENDING_ORDER_HOURS = 24  # an unpaid checkout is canceled after this


@dataclass(frozen=True)
class ConfirmationResult:
    outcome: Literal["paid", "failed", "duplicate", "ignored"]


def active_subscription(db: Session, user: User, *, lock: bool = False) -> Subscription | None:
    query = select(Subscription).where(
        Subscription.user_id == user.id,
        Subscription.status == SubscriptionStatus.active,
        Subscription.current_period_end > utcnow(),
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query.order_by(Subscription.current_period_end.desc()).limit(1))


def allowance_used(db: Session, sub: Subscription) -> int:
    """Events created from this subscription in its current period, counted from their
    orders (app clock, like the period; deleting an event doesn't give the slot back)."""
    return db.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.subscription_id == sub.id,
            Order.event_name.is_not(None),  # renewals carry no event
            Order.status == OrderStatus.paid,
            Order.paid_at >= sub.current_period_start,
        )
    ) or 0


def start_checkout(
    db: Session, user: User, plan_key: str, event_name: str | None, event_date: date | None
) -> tuple[Order, str]:
    plan = PLANS[plan_key]
    if plan.kind == "one_off" and not event_name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Please name your event")
    if plan.kind == "subscription" and active_subscription(db, user) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an active subscription")
    provider = get_provider()
    order = Order(
        id=uuid.uuid4(),
        user_id=user.id,
        plan=plan.key,
        kind=OrderKind.one_off if plan.kind == "one_off" else OrderKind.subscription,
        amount_cents=plan.price_cents,
        currency=CURRENCY,
        vat_rate=VAT_RATE,
        status=OrderStatus.pending,
        provider=provider.name,
        event_name=event_name,
        event_date=event_date,
    )
    checkout = provider.create_checkout(order)
    order.provider_ref = checkout.session_ref
    db.add(order)
    db.commit()
    return order, checkout.url


def apply_confirmation(db: Session, provider_name: str, conf: Confirmation) -> ConfirmationResult:
    """Apply a verified provider confirmation. Idempotent: each provider event id is
    processed once, and an order is fulfilled at most once."""
    first_time = db.scalar(
        pg_insert(WebhookEvent)
        .values(provider=provider_name, provider_event_id=conf.event_id)
        .on_conflict_do_nothing()
        .returning(WebhookEvent.provider_event_id)
    )
    if first_time is None:
        db.rollback()
        return ConfirmationResult("duplicate")
    order = db.scalar(
        select(Order).where(Order.provider == provider_name, Order.provider_ref == conf.session_ref).with_for_update()
    )
    if order is None:
        db.commit()  # remember the event id; nothing to apply
        log.warning("Payment confirmation for an unknown checkout session")
        return ConfirmationResult("ignored")
    if conf.amount_cents != order.amount_cents or conf.currency != order.currency:
        # Paid a different amount than the order says: never fulfil. Needs a human.
        db.commit()
        log.error("Payment confirmation amount/currency mismatch for order %s", order.id)
        return ConfirmationResult("ignored")
    if order.status != OrderStatus.pending:
        db.commit()
        return ConfirmationResult("duplicate")
    if conf.type == "checkout.payment_failed":
        order.failure_code = conf.failure_code or "payment_failed"
        db.commit()
        return ConfirmationResult("failed")
    _fulfil(db, order)
    db.commit()
    return ConfirmationResult("paid")


def _fulfil(db: Session, order: Order) -> None:
    now = utcnow()
    order.status = OrderStatus.paid
    order.paid_at = now
    order.failure_code = None
    user = db.get(User, order.user_id) if order.user_id else None
    if user is None:  # account deleted between checkout and confirmation: refund by hand
        log.error("Paid order %s has no user any more", order.id)
        return
    plan = PLANS[order.plan]
    if order.kind == OrderKind.subscription:
        sub = Subscription(
            user_id=user.id,
            plan=plan.key,
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=SUBSCRIPTION_PERIOD_DAYS),
        )
        db.add(sub)
        db.flush()
        order.subscription_id = sub.id
        if order.event_name:  # the first event, from the allowance
            order.event_id = _create_event(db, user, plan, order.event_name, order.event_date, sub).id
        return
    order.event_id = _create_event(db, user, plan, order.event_name or "My event", order.event_date, None).id


def _create_event(
    db: Session, user: User, plan: Plan, name: str, event_date: date | None, sub: Subscription | None
) -> Event:
    event = new_event(
        db,
        name=name,
        date=event_date,
        created_by=user.id,
        plan=plan.key,
        max_attendees=plan.max_attendees,
        max_photos=plan.max_photos,
        subscription_id=sub.id if sub else None,
    )
    db.flush()
    db.add(EventMember(event_id=event.id, user_id=user.id, role=MemberRole.organizer, status=MemberStatus.approved))
    if user.role == UserRole.attendee:
        user.role = UserRole.organizer  # buyers manage their events (after the Organizer Terms)
    return event


def create_subscription_event(db: Session, user: User, name: str, event_date: date | None) -> Event:
    """An event from the subscription's allowance (no charge; recorded as an order)."""
    sub = active_subscription(db, user, lock=True)  # lock: two clicks can't both use the last slot
    if sub is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You need an active subscription for this")
    plan = PLANS[sub.plan]
    if allowance_used(db, sub) >= plan.events_per_period:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Your plan includes {plan.events_per_period} events per period; this period's are used up",
        )
    event = _create_event(db, user, plan, name, event_date, sub)
    db.add(
        Order(
            user_id=user.id,
            plan=plan.key,
            kind=OrderKind.allowance,
            amount_cents=0,
            currency=CURRENCY,
            vat_rate=VAT_RATE,
            status=OrderStatus.paid,
            provider="subscription",
            event_name=name,
            event_date=event_date,
            event_id=event.id,
            subscription_id=sub.id,
            paid_at=utcnow(),
        )
    )
    db.commit()
    return event


def cancel_subscription(db: Session, user: User) -> Subscription:
    sub = active_subscription(db, user, lock=True)
    if sub is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You have no active subscription")
    if sub.canceled_at is None:
        sub.canceled_at = utcnow()  # runs until the end of the paid period
    db.commit()
    return sub


def run_maintenance(db: Session) -> dict[str, int]:
    """Hourly (beat): cancel abandoned checkouts; end canceled subscriptions at period end
    and renew the others. The fake provider renews successfully; a real provider would
    confirm (or fail) the renewal charge with a webhook instead."""
    now = utcnow()
    abandoned = affected(
        db.execute(
            update(Order)
            .where(Order.status == OrderStatus.pending, Order.created_at < now - timedelta(hours=PENDING_ORDER_HOURS))
            .values(status=OrderStatus.canceled)
        )
    )
    expired = renewed = 0
    due = db.scalars(
        select(Subscription)
        .where(Subscription.status == SubscriptionStatus.active, Subscription.current_period_end <= now)
        .with_for_update(skip_locked=True)
    ).all()
    for sub in due:
        if sub.canceled_at is not None or sub.user_id is None:
            sub.status = SubscriptionStatus.expired
            expired += 1
            continue
        plan = PLANS[sub.plan]
        sub.current_period_start = sub.current_period_end
        sub.current_period_end = sub.current_period_end + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
        db.add(
            Order(
                user_id=sub.user_id,
                plan=plan.key,
                kind=OrderKind.subscription,
                amount_cents=plan.price_cents,
                currency=CURRENCY,
                vat_rate=VAT_RATE,
                status=OrderStatus.paid,
                provider=get_provider().name,
                subscription_id=sub.id,
                paid_at=now,
            )
        )
        renewed += 1
    db.commit()
    return {"abandoned": abandoned, "expired": expired, "renewed": renewed}


def forget_user(db: Session, user: User) -> None:
    """Account deletion: orders stay (invoice retention), unlinked by the FK; a running
    subscription ends now, so nobody is charged for a deleted account."""
    db.execute(
        update(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == SubscriptionStatus.active)
        .values(status=SubscriptionStatus.expired, canceled_at=func.coalesce(Subscription.canceled_at, utcnow()))
    )
