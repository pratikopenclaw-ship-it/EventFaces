"""Per-photo add-on purchases: human editing now, ai_enhance/print later. Mirrors
services/billing/orders.py's checkout/confirmation shape so the existing PaymentProvider
works unchanged, but stays separate because an add-on targets existing photos in an
existing event, not a new event or subscription.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.db import affected
from app.core.security import utcnow
from app.models import AddonKind, AddonOrder, AddonOrderStatus, Event, Photo, PhotoStatus, User, WebhookEvent
from app.services import membership
from app.services.billing.addon_prices import ADDON_PRICES, CURRENCY, VAT_RATE
from app.services.billing.orders import PENDING_ORDER_HOURS
from app.services.billing.provider import Confirmation, get_provider
from app.services.photo_access import viewable_photos

log = logging.getLogger(__name__)

_RETIRED = (PhotoStatus.rejected, PhotoStatus.removed)


@dataclass(frozen=True)
class ConfirmationResult:
    outcome: Literal["paid", "failed", "duplicate", "ignored"]


def _authorize(db: Session, event: Event, buyer: User, kind: AddonKind, photo_ids: list[uuid.UUID]) -> None:
    if not photo_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one photo")
    if len(set(photo_ids)) != len(photo_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Duplicate photo in the same order")
    if membership.can_manage(db, event, buyer):
        # Organizers may buy add-ons for any live photo in their own event, but a photo id
        # from a different event must still be rejected (422, never silently dropped) rather
        # than let a cross-event id ride along in the order. Retired photos (rejected or
        # removed: files deleted by photo_pipeline.retire_photo) are refused too.
        # viewable_photos isn't enough here: for organizers it still includes rejected ones.
        in_event: dict[uuid.UUID, PhotoStatus] = {
            pid: pstatus
            for pid, pstatus in db.execute(
                select(Photo.id, Photo.status).where(Photo.id.in_(photo_ids), Photo.event_id == event.id)
            )
        }
        if set(in_event) != set(photo_ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Photo does not belong to this event")
        if any(s in _RETIRED for s in in_event.values()):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Photo has been removed")
        return
    viewable = {p.id for p in viewable_photos(db, event, buyer, photo_ids)}
    if viewable != set(photo_ids):
        # Either the photo isn't in this event, isn't published, or isn't theirs: never
        # silently drop items from a paid order, so this is a hard refusal, not a filter.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only buy this add-on for your own photos")


def start_checkout(
    db: Session, event: Event, buyer: User, kind: AddonKind, photo_ids: list[uuid.UUID]
) -> tuple[AddonOrder, str]:
    _authorize(db, event, buyer, kind, photo_ids)
    provider = get_provider()
    price = ADDON_PRICES[kind] * len(photo_ids)
    order = AddonOrder(
        id=uuid.uuid4(),
        buyer_user_id=buyer.id,
        event_id=event.id,
        kind=kind,
        photo_ids=photo_ids,
        amount_cents=price,
        currency=CURRENCY,
        vat_rate=VAT_RATE,
        status=AddonOrderStatus.pending,
        provider=provider.name,
    )
    checkout = provider.create_checkout(order)
    order.provider_ref = checkout.session_ref
    db.add(order)
    db.commit()
    return order, checkout.url


def apply_confirmation(db: Session, provider_name: str, conf: Confirmation) -> ConfirmationResult:
    """Apply a verified provider confirmation. Idempotent: each provider event id is
    processed once, and an order is fulfilled at most once. Mirrors
    services/billing/orders.apply_confirmation's shape exactly."""
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
        select(AddonOrder)
        .where(AddonOrder.provider == provider_name, AddonOrder.provider_ref == conf.session_ref)
        .with_for_update()
    )
    if order is None:
        db.commit()  # remember the event id; nothing to apply
        log.warning("Add-on payment confirmation for an unknown checkout session")
        return ConfirmationResult("ignored")
    if conf.amount_cents != order.amount_cents or conf.currency != order.currency:
        db.commit()
        log.error("Add-on payment confirmation amount/currency mismatch for order %s", order.id)
        return ConfirmationResult("ignored")
    if order.status != AddonOrderStatus.pending:
        db.commit()
        return ConfirmationResult("duplicate")
    if conf.type == "checkout.payment_failed":
        order.failure_code = conf.failure_code or "payment_failed"
        db.commit()
        return ConfirmationResult("failed")
    _fulfil(db, order)
    db.commit()
    return ConfirmationResult("paid")


def _fulfil(db: Session, order: AddonOrder) -> None:
    """Mark the order paid. What a paid human_edit order then does (create an editor
    task) is that feature's own concern, added when it lands; this stops at "paid"
    deliberately, per the spec's stated scope for this sub-project."""
    order.status = AddonOrderStatus.paid
    order.paid_at = utcnow()
    order.failure_code = None


def run_maintenance(db: Session) -> dict[str, int]:
    """Hourly (beat, with orders.run_maintenance): cancel abandoned add-on checkouts, so a
    stale session can't be paid days later for a photo retired (or a grant expired) since."""
    abandoned = affected(
        db.execute(
            update(AddonOrder)
            .where(
                AddonOrder.status == AddonOrderStatus.pending,
                AddonOrder.created_at < utcnow() - timedelta(hours=PENDING_ORDER_HOURS),
            )
            .values(status=AddonOrderStatus.canceled)
        )
    )
    db.commit()
    return {"abandoned": abandoned}
