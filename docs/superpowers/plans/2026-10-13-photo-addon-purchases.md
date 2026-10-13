# Photo Add-on Purchases (Payment Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a payment foundation for per-photo add-on purchases (starting with `human_edit`), reusing the existing fake `PaymentProvider`, that both attendees and organizers can use depending on the add-on kind.

**Architecture:** A new `AddonOrder` model and `services/billing/addon_orders.py` mirror the existing `Order`/`services/billing/orders.py` pattern exactly (same provider/provider_ref/status/idempotent-webhook shape), so `FakeProvider` works on both unchanged. A new `services/billing/addon_prices.py` holds per-kind pricing, separate from `plans.py`. The existing `/api/billing/webhook/fake` route is extended to route a confirmation to whichever table's `provider_ref` matches, instead of adding a second webhook endpoint.

**Tech Stack:** FastAPI, SQLAlchemy 2 (sync), Alembic, pytest, the existing `FakeProvider`/`PaymentProvider` from `app/services/billing/provider.py`.

**Spec:** `docs/superpowers/specs/2026-10-13-photo-addon-purchases-design.md`

## Global Constraints

- Reuse `app/services/billing/provider.py`'s `FakeProvider`/`PaymentProvider` unchanged — no new provider code.
- No real payment processor integration.
- No new generic "Purchasable" abstraction — only `AddonKind.human_edit` ships now.
- Prices are gross (incl. VAT), `EXAMPLE_PRICES = True` until the operator sets real ones, same convention as `plans.py`.
- `AddonOrder.event_id` cascades on event delete (`ondelete="CASCADE"`) — no separate retention-sweep wiring needed for this table.
- Every event-scoped route must depend on `MemberEvent` or `ManagedEvent` from `app/api/deps.py` (root `CLAUDE.md` security invariant).
- `backend/openapi.json` must be regenerated (`python -m app.cli export-openapi`) after the new routes land, or `tests/test_openapi_contract.py` fails.
- New ops must be added to `tests/test_authz_matrix.py::OPS` (both transports) and rate-limited ones to `tests/test_endpoint_contracts.py::RATE_LIMITED`.

## Review Focus

- An attendee tries to buy a `human_edit` for a photo they can't view (not their upload, no grant, not published) — must be refused, not silently scoped to zero items.
- A buyer passes `photo_ids` containing photos from a different event than the one in the URL — must be rejected, not silently filtered (unlike `viewable_photos`, which filters; a checkout must not silently charge for fewer photos than requested).
- Two webhook confirmations for the same `provider_ref` (replay) — second one must be a no-op, not a double-fulfil, and must not be charged against the wrong table's `WebhookEvent` dedupe.
- A webhook confirmation whose `session_ref` matches neither an `Order` nor an `AddonOrder` — must be `ignored`, not a 500.
- An organizer buys `human_edit` for a photo removed/retired between checkout and payment — `_fulfil` must not act on a removed photo.

---

## Task 1: Enums and the `AddonOrder` model

**Files:**
- Modify: `app/models/enums.py` (append `AddonKind`, `AddonOrderStatus`)
- Create: `app/models/addon_order.py`
- Modify: `app/models/__init__.py` (export `AddonOrder`, `AddonKind`, `AddonOrderStatus`)
- Create: `alembic/versions/0015_addon_orders.py`
- Test: `tests/test_migrations.py` (existing test; no new code — it compares schema vs. metadata automatically once the model is added)

**Interfaces:**
- Produces: `AddonKind` (`str, enum.Enum`, member `human_edit = "human_edit"`), `AddonOrderStatus` (`str, enum.Enum`, members `pending`, `paid`, `canceled`), `AddonOrder` SQLAlchemy model with columns: `id: uuid.UUID`, `buyer_user_id: uuid.UUID | None`, `event_id: uuid.UUID`, `kind: AddonKind`, `photo_ids: list[uuid.UUID]`, `amount_cents: int`, `currency: str`, `vat_rate: int`, `status: AddonOrderStatus`, `provider: str`, `provider_ref: str | None`, `failure_code: str | None`, `created_at: datetime`, `paid_at: datetime | None`.

- [ ] **Step 1: Add the two enums**

In `app/models/enums.py`, append at the end:

```python
class AddonKind(str, enum.Enum):
    human_edit = "human_edit"  # ai_enhance, print added when those sub-projects land


class AddonOrderStatus(str, enum.Enum):
    pending = "pending"  # checkout started, no confirmed payment yet
    paid = "paid"
    canceled = "canceled"
```

- [ ] **Step 2: Write the model**

Create `app/models/addon_order.py`:

```python
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
```

- [ ] **Step 3: Export from `app/models/__init__.py`**

Add to the enum import block: `AddonKind,` and `AddonOrderStatus,` (alphabetical, right after the existing imports — before `FeedbackVerdict` and after... actually insert alphabetically: `AddonKind` and `AddonOrderStatus` both sort before `FeedbackVerdict` and after nothing since the list starts with `FeedbackVerdict` currently — they become the new first two entries).

Add `from app.models.addon_order import AddonOrder` as its own import line (alphabetically before `from app.models.billing import ...`).

Add `"AddonKind"`, `"AddonOrder"`, `"AddonOrderStatus"` to `__all__` (alphabetically — they become the first three entries, before `"AuthToken"`).

- [ ] **Step 4: Write the migration**

Create `alembic/versions/0015_addon_orders.py`:

```python
"""addon_orders: per-photo add-on purchases (human editing, later ai_enhance/print)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
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
```

- [ ] **Step 5: Apply the migration and verify schema/model agreement**

Run: `docker compose exec api alembic upgrade head`
Expected: migration `0015` applies cleanly.

Run: `docker compose exec api pytest tests/test_migrations.py -q`
Expected: PASS (confirms the model's columns/indexes match the migration's).

- [ ] **Step 6: Commit**

```bash
git add app/models/enums.py app/models/addon_order.py app/models/__init__.py alembic/versions/0015_addon_orders.py
git commit -m "feat: add AddonOrder model for per-photo add-on purchases

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Add-on price list

**Files:**
- Create: `app/services/billing/addon_prices.py`
- Test: `tests/test_billing.py` (add a small new test class/functions in this file — it already covers `plans.py`-style pricing)

**Interfaces:**
- Consumes: `AddonKind` from Task 1.
- Produces: `ADDON_PRICES: dict[AddonKind, int]`, `ADDON_EXAMPLE_PRICES: bool` (mirrors `plans.EXAMPLE_PRICES`), `addon_price_cents(kind: AddonKind) -> int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_billing.py`:

```python
from app.models import AddonKind
from app.services.billing.addon_prices import ADDON_PRICES, addon_price_cents


def test_addon_price_lookup_matches_the_table():
    assert addon_price_cents(AddonKind.human_edit) == ADDON_PRICES[AddonKind.human_edit]
    assert ADDON_PRICES[AddonKind.human_edit] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec api pytest tests/test_billing.py::test_addon_price_lookup_matches_the_table -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.billing.addon_prices'`

- [ ] **Step 3: Write the price list**

Create `app/services/billing/addon_prices.py`:

```python
"""Per-item add-on pricing (services/billing/addon_orders.py). Separate from plans.py:
add-on pricing is per item, not per plan, and future kinds (ai_enhance, print) may price
by size or count rather than flatly — kept here until that shape is known.

Prices are gross (incl. VAT); EXAMPLE until the owner sets real ones (ADDON_EXAMPLE_PRICES).
"""

from app.models import AddonKind
from app.services.billing.plans import CURRENCY, VAT_RATE  # noqa: F401 - re-exported for callers

ADDON_EXAMPLE_PRICES = True

ADDON_PRICES: dict[AddonKind, int] = {
    AddonKind.human_edit: 999,  # per photo, gross cents
}


def addon_price_cents(kind: AddonKind) -> int:
    return ADDON_PRICES[kind]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec api pytest tests/test_billing.py::test_addon_price_lookup_matches_the_table -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/billing/addon_prices.py tests/test_billing.py
git commit -m "feat: add per-item add-on price list

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `addon_orders` service — `start_checkout` with authorization

**Files:**
- Create: `app/services/billing/addon_orders.py`
- Test: `tests/test_addon_orders.py`

**Interfaces:**
- Consumes: `AddonOrder`, `AddonKind`, `AddonOrderStatus` (Task 1); `addon_price_cents` (Task 2); `get_provider()`, `Confirmation` (`app/services/billing/provider.py`, unchanged); `photo_access.viewable_photos(db, event, user, photo_ids) -> list[Photo]`; `membership.can_manage(db, event, user) -> bool`.
- Produces: `start_checkout(db: Session, event: Event, buyer: User, kind: AddonKind, photo_ids: list[uuid.UUID]) -> tuple[AddonOrder, str]` (raises `HTTPException` 403/422 on bad input); `ConfirmationResult` (same shape as `orders.ConfirmationResult`, duplicated here deliberately — see Task 4).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_addon_orders.py`:

```python
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import AddonKind, AddonOrder, AddonOrderStatus, Event, PhotoStatus, User
from app.services.billing import addon_orders
from app.services.billing.addon_prices import ADDON_PRICES
from tests.helpers import make_event_with_photo  # see Step 1a below for the fixture this needs


def test_organizer_can_buy_addon_for_any_event_photo(db: Session, organizer: User, event: Event, photo):
    order, url = addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [photo.id])
    assert order.status == AddonOrderStatus.pending
    assert order.amount_cents == ADDON_PRICES[AddonKind.human_edit]
    assert order.event_id == event.id
    assert order.photo_ids == [photo.id]
    assert url.startswith("/checkout/test/")


def test_attendee_can_buy_addon_only_for_their_own_viewable_photo(db: Session, attendee_member: User, event: Event, own_photo, someone_elses_photo):
    order, _ = addon_orders.start_checkout(db, event, attendee_member, AddonKind.human_edit, [own_photo.id])
    assert order.photo_ids == [own_photo.id]

    with pytest.raises(HTTPException) as exc:
        addon_orders.start_checkout(db, event, attendee_member, AddonKind.human_edit, [someone_elses_photo.id])
    assert exc.value.status_code == 403


def test_photo_ids_from_another_event_are_rejected_not_silently_dropped(db: Session, organizer: User, event: Event, other_event_photo):
    with pytest.raises(HTTPException) as exc:
        addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [other_event_photo.id])
    assert exc.value.status_code == 422


def test_empty_photo_ids_is_rejected(db: Session, organizer: User, event: Event):
    with pytest.raises(HTTPException) as exc:
        addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [])
    assert exc.value.status_code == 422
```

Use this project's existing fixtures (`make_user`, `make_event`, `add_member` from `tests/conftest.py`) rather than the placeholder names above — write the actual fixtures/setup inline in the test file following the style already used in `tests/test_billing.py` and `tests/test_search.py` (e.g. `make_user(db, role=...)`, `make_event(db, ...)`, uploading/creating a `Photo` row directly with `status=PhotoStatus.published`, and a `SearchGrant` for the "own photo" case per `services/photo_access.py`). Match whatever helper names `conftest.py` actually exposes.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_addon_orders.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.billing.addon_orders'`

- [ ] **Step 3: Write `start_checkout`**

Create `app/services/billing/addon_orders.py`:

```python
"""Per-photo add-on purchases: human editing now, ai_enhance/print later. Mirrors
services/billing/orders.py's checkout/confirmation shape so the existing PaymentProvider
works unchanged, but stays separate because an add-on targets existing photos in an
existing event, not a new event or subscription.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import AddonKind, AddonOrder, AddonOrderStatus, Event, PhotoStatus, User, WebhookEvent
from app.services import membership
from app.services.billing.addon_prices import ADDON_PRICES, CURRENCY, VAT_RATE
from app.services.billing.provider import Confirmation, get_provider
from app.services.photo_access import viewable_photos

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfirmationResult:
    outcome: Literal["paid", "failed", "duplicate", "ignored"]


def _authorize(db: Session, event: Event, buyer: User, kind: AddonKind, photo_ids: list[uuid.UUID]) -> None:
    if not photo_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one photo")
    if len(set(photo_ids)) != len(photo_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Duplicate photo in the same order")
    if membership.can_manage(db, event, buyer):
        return  # organizers may buy add-ons for any (non-removed) photo in their event
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
```

Note: `viewable_photos` already excludes `PhotoStatus.removed` rows, so a removed photo id simply won't appear in `viewable`, which correctly 403s for an attendee. For an organizer, `membership.can_manage` short-circuits before that check — a removed photo bought by an organizer is handled in Task 4's `_fulfil`, not here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_addon_orders.py -v`
Expected: PASS for the four tests written so far (the confirmation-flow tests come in Task 4).

- [ ] **Step 5: Commit**

```bash
git add app/services/billing/addon_orders.py tests/test_addon_orders.py
git commit -m "feat: add_on checkout with per-kind buyer authorization

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `addon_orders` service — idempotent `apply_confirmation` and `_fulfil`

**Files:**
- Modify: `app/services/billing/addon_orders.py`
- Test: `tests/test_addon_orders.py`

**Interfaces:**
- Consumes: `Confirmation` (`app/services/billing/provider.py`); `WebhookEvent` (`app/models`).
- Produces: `apply_confirmation(db: Session, provider_name: str, conf: Confirmation) -> ConfirmationResult`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_addon_orders.py`:

```python
from app.services.billing.provider import get_provider


def test_confirmation_marks_order_paid(db: Session, organizer: User, event: Event, photo):
    order, _ = addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [photo.id])
    provider = get_provider()
    raw, headers = provider.confirmation_for(order, "4242424242424242")
    result = addon_orders.apply_confirmation(db, provider.name, provider.parse_confirmation(raw, headers))
    assert result.outcome == "paid"
    db.refresh(order)
    assert order.status == AddonOrderStatus.paid
    assert order.paid_at is not None


def test_replayed_confirmation_is_a_duplicate_not_a_double_fulfil(db: Session, organizer: User, event: Event, photo):
    order, _ = addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [photo.id])
    provider = get_provider()
    raw, headers = provider.confirmation_for(order, "4242424242424242")
    conf = provider.parse_confirmation(raw, headers)
    first = addon_orders.apply_confirmation(db, provider.name, conf)
    second = addon_orders.apply_confirmation(db, provider.name, conf)
    assert first.outcome == "paid"
    assert second.outcome == "duplicate"


def test_confirmation_for_unknown_session_is_ignored_not_an_error(db: Session):
    provider = get_provider()
    from app.services.billing.provider import Confirmation

    conf = Confirmation(event_id="evt_nope", type="checkout.completed", session_ref="fcs_doesnotexist", amount_cents=100, currency="EUR")
    result = addon_orders.apply_confirmation(db, provider.name, conf)
    assert result.outcome == "ignored"


def test_failed_payment_sets_failure_code_not_paid(db: Session, organizer: User, event: Event, photo):
    order, _ = addon_orders.start_checkout(db, event, organizer, AddonKind.human_edit, [photo.id])
    provider = get_provider()
    raw, headers = provider.confirmation_for(order, "4000000000000002")  # published "card_declined" test card
    result = addon_orders.apply_confirmation(db, provider.name, provider.parse_confirmation(raw, headers))
    assert result.outcome == "failed"
    db.refresh(order)
    assert order.status == AddonOrderStatus.pending
    assert order.failure_code == "card_declined"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_addon_orders.py -v -k confirmation`
Expected: FAIL with `AttributeError: module 'app.services.billing.addon_orders' has no attribute 'apply_confirmation'`

- [ ] **Step 3: Implement `apply_confirmation` and `_fulfil`**

Append to `app/services/billing/addon_orders.py`:

```python
from app.core.security import utcnow


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
```

Note: deliberately no "does the photo still exist / still published" re-check inside `_fulfil` for this sub-project — there is no per-kind fulfilment action yet to guard (unlike `index_photo`'s re-check, which guards a real write). Sub-project 2 (human editing) must add that re-check when it adds the actual editor-task creation in its own `_fulfil` extension, since that is where a removed photo would otherwise still get a task created for it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_addon_orders.py -v`
Expected: PASS (all tests in the file, Tasks 3 and 4 combined)

- [ ] **Step 5: Commit**

```bash
git add app/services/billing/addon_orders.py tests/test_addon_orders.py
git commit -m "feat: idempotent add-on payment confirmation handling

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Schemas for the add-on API

**Files:**
- Modify: `app/schemas/billing.py`
- Test: none (pure pydantic models; exercised by Task 6's route tests)

**Interfaces:**
- Consumes: `AddonKind`, `AddonOrderStatus` (Task 1).
- Produces: `AddonCheckoutIn`, `AddonCheckoutOut`, `AddonOrderOut`, `AddonTestCheckoutOut` (reuses `TestPaymentIn`/`Outcome`/`TestPaymentOut`-style naming already in this file).

- [ ] **Step 1: Add the schemas**

Append to `app/schemas/billing.py` (add `from app.models import AddonKind, AddonOrderStatus` to the existing `from app.models import ...` line at the top):

```python
class AddonCheckoutIn(BaseModel):
    kind: AddonKind
    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class AddonCheckoutOut(BaseModel):
    order_id: uuid.UUID
    checkout_url: str


class AddonOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    kind: AddonKind
    photo_ids: list[uuid.UUID]
    amount_cents: int
    vat_cents: int = 0
    currency: str
    vat_rate: int
    status: AddonOrderStatus
    failure_code: str | None
    created_at: dt.datetime
    paid_at: dt.datetime | None


class AddonTestCheckoutOut(BaseModel):
    order: AddonOrderOut
    test_cards: list[str]


class AddonTestPaymentOut(BaseModel):
    outcome: Outcome
    order: AddonOrderOut
```

The `max_length=50` on `photo_ids` is a pragmatic cap (no spec requirement for a specific number, but an unbounded array in a single order is an unforced resource risk) — reuse this value verbatim, don't invent another.

- [ ] **Step 2: Verify the module imports cleanly**

Run: `docker compose exec api python -c "import app.schemas.billing"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add app/schemas/billing.py
git commit -m "feat: add schemas for the add-on checkout API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Routes — checkout, test-checkout/pay, and webhook routing

**Files:**
- Modify: `app/api/routes/billing.py`
- Test: `tests/test_addon_orders.py` (route-level tests, using the existing test client fixture `client`/`login_as` from `tests/conftest.py`)

**Interfaces:**
- Consumes: `addon_orders.start_checkout`, `addon_orders.apply_confirmation` (Tasks 3–4); `AddonCheckoutIn`, `AddonCheckoutOut`, `AddonOrderOut`, `AddonTestCheckoutOut`, `AddonTestPaymentOut` (Task 5); `MemberEvent` (`app/api/deps.py`, unchanged).
- Produces: `POST /api/events/{event_id}/addons/checkout`, `GET /api/billing/addon-checkout/{session_ref}`, `POST /api/billing/addon-checkout/{session_ref}/pay`; extends the existing `POST /api/billing/webhook/fake` to route to `AddonOrder` confirmations too.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_addon_orders.py` (uses the project's existing `client`, `login_as`, `make_user`, `make_event`, `add_member` fixtures from `tests/conftest.py` — follow the exact calling convention already used in `tests/test_billing.py`'s route-level tests for `test_checkout`/`test_pay`):

```python
def test_addon_checkout_route_then_pay_marks_paid(client, login_as, organizer, event, photo):
    cookies = login_as(organizer)
    resp = client.post(
        f"/api/events/{event.id}/addons/checkout",
        json={"kind": "human_edit", "photo_ids": [str(photo.id)]},
        cookies=cookies,
    )
    assert resp.status_code == 200
    session_ref = resp.json()["checkout_url"].rsplit("/", 1)[-1]

    get_resp = client.get(f"/api/billing/addon-checkout/{session_ref}", cookies=cookies)
    assert get_resp.status_code == 200
    assert get_resp.json()["test_cards"]

    pay_resp = client.post(
        f"/api/billing/addon-checkout/{session_ref}/pay",
        json={"card_number": "4242 4242 4242 4242", "expiry": "12/30", "cvc": "123"},
        cookies=cookies,
    )
    assert pay_resp.status_code == 200
    assert pay_resp.json()["outcome"] == "paid"
    assert pay_resp.json()["order"]["status"] == "paid"


def test_addon_checkout_rejects_non_member(client, login_as, make_user, event, photo):
    stranger = make_user()
    cookies = login_as(stranger)
    resp = client.post(
        f"/api/events/{event.id}/addons/checkout",
        json={"kind": "human_edit", "photo_ids": [str(photo.id)]},
        cookies=cookies,
    )
    assert resp.status_code == 403


Follow whatever session-access fixture `tests/test_billing.py`'s webhook test already uses to
fetch the `Order` row after posting to `/api/billing/webhook/fake` (likely a `db` fixture
queried directly), applied here to `AddonOrder`:

```python
def test_webhook_routes_addon_confirmation_to_addon_order(client, login_as, db, organizer, event, photo):
    cookies = login_as(organizer)
    resp = client.post(
        f"/api/events/{event.id}/addons/checkout",
        json={"kind": "human_edit", "photo_ids": [str(photo.id)]},
        cookies=cookies,
    )
    session_ref = resp.json()["checkout_url"].rsplit("/", 1)[-1]
    order = db.scalar(select(AddonOrder).where(AddonOrder.provider_ref == session_ref))

    provider = get_provider()
    raw, headers = provider.confirmation_for(order, "4242424242424242")
    webhook_resp = client.post("/api/billing/webhook/fake", content=raw, headers=headers)
    assert webhook_resp.status_code == 200
    assert webhook_resp.json()["status"] == "paid"
    db.refresh(order)
    assert order.status == AddonOrderStatus.paid
```

(Add `from sqlalchemy import select` and `from app.models import AddonOrder` to the test file's imports if not already present from earlier tasks.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_addon_orders.py -v -k "route or webhook"`
Expected: FAIL with 404s (routes don't exist yet).

- [ ] **Step 3: Implement the routes**

In `app/api/routes/billing.py`:

Add to the imports:
```python
from app.api.deps import DB, ManagedEvent, MemberEvent, VerifiedUser
from app.models import AddonOrder, AddonOrderStatus, Order, OrderStatus, Subscription, User
from app.schemas.billing import (
    AddonCheckoutIn,
    AddonCheckoutOut,
    AddonOrderOut,
    AddonTestCheckoutOut,
    AddonTestPaymentOut,
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
from app.services.billing import addon_orders, limits, orders
```
(Keep `ManagedEvent` for the existing `event_usage` route; add `MemberEvent` alongside it.)

Add helper and routes (place after the existing `_own_order`/`order_out` helpers):

```python
def addon_order_out(order: AddonOrder) -> AddonOrderOut:
    out = AddonOrderOut.model_validate(order)
    return out.model_copy(update={"vat_cents": vat_part(order.amount_cents, order.vat_rate)})


def _own_addon_order(db: DB, user: User, session_ref: str) -> AddonOrder:
    order = db.scalar(select(AddonOrder).where(AddonOrder.buyer_user_id == user.id, AddonOrder.provider_ref == session_ref))
    if order is None:
        raise NOT_FOUND
    return order


@router.post("/events/{event_id}/addons/checkout", response_model=AddonCheckoutOut)
def addon_checkout(event: MemberEvent, body: AddonCheckoutIn, user: VerifiedUser, db: DB) -> AddonCheckoutOut:
    rate_limit.enforce(f"addon-checkout:{user.id}", rate_limit.Limit.parse(get_settings().checkout_rate_limit))
    order, url = addon_orders.start_checkout(db, event, user, body.kind, body.photo_ids)
    return AddonCheckoutOut(order_id=order.id, checkout_url=url)


@router.get("/billing/addon-checkout/{session_ref}", response_model=AddonTestCheckoutOut)
def addon_test_checkout(session_ref: str, user: VerifiedUser, db: DB) -> AddonTestCheckoutOut:
    if not get_provider().test_mode:
        raise NOT_FOUND
    return AddonTestCheckoutOut(order=addon_order_out(_own_addon_order(db, user, session_ref)), test_cards=list(TEST_CARDS))


@router.post("/billing/addon-checkout/{session_ref}/pay", response_model=AddonTestPaymentOut)
def addon_test_pay(session_ref: str, body: TestPaymentIn, user: VerifiedUser, db: DB) -> AddonTestPaymentOut:
    provider = get_provider()
    if not provider.test_mode:
        raise NOT_FOUND
    rate_limit.enforce(f"addon-pay:{user.id}", rate_limit.Limit.parse(get_settings().payment_attempt_rate_limit))
    order = _own_addon_order(db, user, session_ref)
    if order.status != AddonOrderStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This checkout is already closed")
    try:
        raw, headers = provider.confirmation_for(order, body.card_number)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This is a test checkout: use one of the test card numbers shown. No real card can be charged here.",
        ) from None
    db.rollback()
    result = addon_orders.apply_confirmation(db, provider.name, provider.parse_confirmation(raw, headers))
    return AddonTestPaymentOut(outcome=result.outcome, order=addon_order_out(_own_addon_order(db, user, session_ref)))
```

Modify the existing `fake_webhook` function to route by which table's `provider_ref` matches, instead of always calling `orders.apply_confirmation`:

```python
@router.post("/billing/webhook/fake", response_model=WebhookOut, openapi_extra=WEBHOOK_OPENAPI)
async def fake_webhook(request: Request, db: DB) -> WebhookOut:
    """Server-to-server payment confirmation. No session: authenticated only by its HMAC
    signature and timestamp (replays and forgeries are refused; each event applies once).
    Exempt from CSRF because it carries no cookies (api/csrf.py). Routes to whichever
    table's provider_ref matches: an Order (event purchase) or an AddonOrder (photo add-on) —
    never both, so each webhook event id is only ever inserted into WebhookEvent once."""
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"webhook:{ip}", rate_limit.Limit.parse(get_settings().webhook_rate_limit))
    raw = await _read_body(request)
    provider = get_provider()
    try:
        conf = provider.parse_confirmation(raw, dict(request.headers))
    except InvalidConfirmation:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature or payload") from None
    is_addon_order = db.scalar(
        select(AddonOrder.id).where(AddonOrder.provider == provider.name, AddonOrder.provider_ref == conf.session_ref)
    )
    if is_addon_order is not None:
        result = await run_in_threadpool(addon_orders.apply_confirmation, db, provider.name, conf)
    else:
        result = await run_in_threadpool(orders.apply_confirmation, db, provider.name, conf)
    return WebhookOut(status=result.outcome)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_addon_orders.py -v`
Expected: PASS (all tests, the whole file)

Run: `docker compose exec api pytest tests/test_billing.py -v`
Expected: PASS (confirms the webhook change didn't break the existing `Order` confirmation path)

- [ ] **Step 5: Commit**

```bash
git add app/api/routes/billing.py tests/test_addon_orders.py
git commit -m "feat: add-on checkout routes and shared webhook routing

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Authorization matrix, rate-limit contract, and OpenAPI export

**Files:**
- Modify: `tests/test_authz_matrix.py`
- Modify: `tests/test_endpoint_contracts.py`
- Regenerate: `backend/openapi.json` (via CLI, not hand-edited)

**Interfaces:**
- Consumes: the three new routes from Task 6.

- [ ] **Step 1: Add the new ops to the authorization matrix**

In `tests/test_authz_matrix.py`, in the `OPS` list, right after the existing `# --- billing ...` block (near the other `Op("GET", f"/api/events/{E}/...", "MEMBER")` entries so it sits next to its sibling event-scoped ops), add:

```python
    Op("POST", f"/api/events/{E}/addons/checkout", "MEMBER", json={"kind": "human_edit", "photo_ids": ["{random_id}"]}),
    Op("GET", "/api/billing/addon-checkout/fcs_not-a-session", "VERIFIED"),
    Op("POST", "/api/billing/addon-checkout/fcs_not-a-session/pay", "VERIFIED", json={"card_number": "4242 4242 4242 4242", "expiry": "12/30", "cvc": "123"}),
```

Check the file's placeholder-substitution section (the regex/replacement table near the bottom, same one that maps `{random_id}` and `{event_a}`) already covers `{random_id}` as a valid photo id placeholder — it does, since other ops like `Op("GET", "/api/billing/orders/{random_id}", "VERIFIED")` already use it. No new placeholder entries needed. `MEMBER` on the checkout op is intentional even though the service further restricts attendees to their own photos — the matrix only verifies the *dependency* (`MemberEvent`) is present, not kind-specific business rules, exactly like the existing `Op("POST", f"/api/events/{E}/search?source=upload", "MEMBER", ...)`.

- [ ] **Step 2: Run the matrix test**

Run: `docker compose exec api pytest tests/test_authz_matrix.py -v`
Expected: PASS

- [ ] **Step 3: Add the rate-limited routes to the endpoint contract test**

In `tests/test_endpoint_contracts.py`, add to the `RATE_LIMITED` set (next to the existing `("POST", "/api/billing/checkout")` line):

```python
    ("POST", "/api/events/{event_a}/addons/checkout"),
    ("POST", "/api/billing/addon-checkout/fcs_not-a-session/pay"),
```

- [ ] **Step 4: Run the contract test**

Run: `docker compose exec api pytest tests/test_endpoint_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate the OpenAPI export**

Run: `docker compose exec api python -m app.cli export-openapi`

Run: `docker compose exec api pytest tests/test_openapi_contract.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend test suite**

Run: `docker compose exec api pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_authz_matrix.py tests/test_endpoint_contracts.py backend/openapi.json
git commit -m "test: cover add-on routes in the authz matrix and endpoint contracts

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Guard mutation check (manual)

**Files:** none modified — this is a verification-only task per the project's "security guards were mutation-tested" convention.

- [ ] **Step 1: Temporarily remove the attendee authorization check**

In `app/services/billing/addon_orders.py::_authorize`, comment out the `if viewable != set(photo_ids): raise HTTPException(...)` block.

- [ ] **Step 2: Confirm a test fails**

Run: `docker compose exec api pytest tests/test_addon_orders.py::test_attendee_can_buy_addon_only_for_their_own_viewable_photo -v`
Expected: FAIL (proves the test actually exercises the guard).

- [ ] **Step 3: Restore the check**

Undo the comment-out from Step 1.

- [ ] **Step 4: Confirm the test passes again**

Run: `docker compose exec api pytest tests/test_addon_orders.py::test_attendee_can_buy_addon_only_for_their_own_viewable_photo -v`
Expected: PASS

No commit for this task — nothing changed in the end; it's a one-time proof the guard is load-bearing, done once before the branch is considered finished.

---

## Final check

- [ ] Run `docker compose exec api pytest -q` once more after all tasks — full green.
- [ ] Run `cd frontend && npm run lint && npx next typegen && npx tsc --noEmit && npm run build` — this plan touches no frontend code, so this is a regression check only, expected to pass unchanged.
- [ ] Confirm `scripts/security-scan.sh` still reports 18/18 PASS.
