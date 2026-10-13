# Photo add-on purchases: payment foundation

Status: draft, pending user review.

## Purpose

EventFaces will offer three new paid photo add-ons: human-based photo editing, AI photo
enhancement, and print-and-ship ordering. Each is its own sub-project with its own spec and
plan. This spec covers only the shared foundation they all need: a way to charge for a
per-photo (or per-item) purchase, separate from the existing per-event/subscription billing in
`services/billing`.

Buyer model: either the attendee (e.g. ordering prints of their own matched photos) or the
organizer (e.g. bulk AI enhancement for the whole gallery) can be the buyer, depending on the
feature — this model must support both without assuming one.

Payment processor: reuse the existing fake/test `PaymentProvider` (`services/billing/provider.py`)
unchanged. No real processor integration in this sub-project; swapping in a real provider later
only requires implementing `PaymentProvider` and does not touch anything built here.

## Non-goals

- No new generic "Purchasable" polymorphic abstraction. Only one concrete add-on kind
  (`human_edit`) ships with this sub-project; `ai_enhance` and `print` are added as their own
  `AddonKind` values when those sub-projects land, once their actual data needs are known.
- No real payment processor.
- No iOS purchase UI (App Store rules unchanged) — see Web checkout handoff below.

## Data model

New file `backend/app/models/addon_order.py`:

```python
class AddonKind(enum.Enum):
    human_edit = "human_edit"
    # ai_enhance, print added when those sub-projects land

class AddonOrderStatus(enum.Enum):
    pending = "pending"
    paid = "paid"
    canceled = "canceled"

class AddonOrder(Base):
    __tablename__ = "addon_orders"

    id: UUID (pk)
    buyer_user_id: UUID | None, FK users.id ON DELETE SET NULL, indexed
    event_id: UUID, FK events.id ON DELETE CASCADE, indexed
        # every add-on is scoped to one event; event deletion/retention removes its add-on orders too
    kind: AddonKind
    photo_ids: ARRAY(UUID)  # one or more target photos; non-empty, checked
    amount_cents: int  # gross, incl. VAT — CHECK >= 0
    currency: str(3)   # CHECK matches ^[A-Z]{3}$
    vat_rate: int
    status: AddonOrderStatus, default pending
    provider: str(20)
    provider_ref: str(100) | None, unique
    failure_code: str(40) | None
    created_at: datetime, server_default now()
    paid_at: datetime | None
```

This deliberately mirrors `Order`'s shape (same provider/provider_ref/amount/status pattern) so
`FakeProvider.create_checkout`/`parse_confirmation` work on it unchanged — they only read
`provider_ref`, `amount_cents`, `currency` by attribute, no `Order`-specific typing is required
in practice (the `Order` type hint in `provider.py`'s signatures will be widened to a
`Protocol` with those three attributes, or `AddonOrder` passed as a structurally-compatible
object — decided in the implementation plan).

`photo_ids` as an array (rather than a join table) because an add-on order's items never need
independent querying beyond "does this order include photo X" and are always read as a whole
with ownership/count checks are enforced at order-creation time, not per-row — a join table
would be unused flexibility.

## Fulfilment flow

New file `backend/app/services/billing/addon_orders.py`, mirroring `orders.py`'s pattern:

- `start_checkout(db, buyer, event, kind, photo_ids)`: validates the buyer's right to buy this
  add-on for these photos (membership + per-kind authorization, e.g. "human_edit" by an
  attendee is allowed only for photos where they're the matched subject or uploader, per
  `photo_access.viewable_photos`; by an organizer it's allowed for any photo in their event).
  Looks up price via a new `addon_prices.py` (see below), creates a `pending` `AddonOrder`, gets
  a checkout session from `get_provider()`, returns `(order, checkout_url)`.
- `apply_confirmation(db, provider_name, conf)`: same idempotency pattern as `orders.py`
  (`WebhookEvent` insert-or-ignore keyed on provider+event id, row-locked order lookup by
  `provider`+`provider_ref`, amount/currency check, status check) but looked up against
  `AddonOrder` instead of `Order`, and a **separate webhook event-id namespace is not needed** —
  `WebhookEvent`'s primary key is already `(provider, provider_event_id)` and the fake
  provider's event ids are random per-checkout, so `Order` and `AddonOrder` confirmations never
  collide; the handler tries `Order` first, then `AddonOrder`, by `provider_ref` lookup.
- `_fulfil(db, order)`: for `kind == human_edit`, marks the order paid and creates a row in a
  `human_edit_requests` table (defined in that sub-project's own spec) — this sub-project stops
  at "the order is paid"; what paid-fulfilment does per kind is each feature's own concern.

## Pricing

New file `backend/app/services/billing/addon_prices.py`:

```python
ADDON_PRICES: dict[AddonKind, int] = {
    AddonKind.human_edit: 999,  # EXAMPLE price, gross cents, per photo
}
```

Kept separate from `plans.py` because add-on pricing is per-item, not per-plan, and each add-on
kind may price differently (flat fee vs. per-photo vs. size-dependent for prints) — forcing
them into one shared structure now would guess at shapes sub-projects 3 and 4 haven't designed
yet. `EXAMPLE_PRICES = True` convention from `plans.py` applies here too; same pricing-page
disclaimer requirement.

## Web checkout handoff (iOS)

The iOS app has no purchase UI. Any add-on purchase initiated from the app opens the
corresponding web checkout URL (`/checkout/addon/<order_id>` or similar, mirroring the existing
`/checkout/test/<ref>` fake-provider page) in the system browser via a deep link the app already
knows how to construct, the same way a user would reach it from the web gallery. No new iOS
networking code beyond "open this URL" is needed for this sub-project.

## GDPR / retention

`AddonOrder.event_id` cascades on event deletion, so add-on orders disappear with their event
automatically — no separate `retention.py` wiring needed for this table itself. However:
`services/retention.expire_event`, `account.delete_account`, and consent-withdrawal paths must
all be checked when `human_edit_requests` (and later `ai_enhance`/`print` derivative tables) are
added, since *those* may hold biometric-adjacent derivative data (e.g. an enhanced photo) that
outlives the simple order record. This is flagged here for sub-project 2/3/4 to pick up, not
solved in this spec.

## Authorization

No new `MemberEvent`/`ManagedEvent` dependency type is needed — `start_checkout` takes the
already-authenticated user and event, and does its own per-kind, per-photo check inline (reusing
`photo_access.viewable_photos` for attendee-side checks and `ManagedEvent`-style organizer checks
for organizer-side ones). `tests/test_authz_matrix.py`'s `OPS` list must include the new checkout
and webhook endpoints.

## API surface (for this sub-project only)

- `POST /api/events/{event_id}/addons/checkout` — body: `{kind, photo_ids}`; auth required
  (cookie or mobile bearer); returns `{order_id, checkout_url}`.
- `POST /api/webhooks/fake-addon` (or reuse the existing fake webhook route, routed by looking up
  `Order` then `AddonOrder`) — CSRF-exempt per existing webhook pattern.
- `export-openapi` must be re-run after these land (iOS client source, even though iOS only
  opens the URL — the CLI gate in `tests/test_openapi_contract.py` still applies).

## Testing

- `tests/test_billing.py`-style: start_checkout authorization (attendee allowed only for own
  photos, organizer allowed for any), price lookup, idempotent `apply_confirmation` (duplicate
  webhook, amount mismatch, unknown session), fake provider round-trip (test card → paid).
- `tests/test_authz_matrix.py`: new ops added, both transports.
- Guard mutation-check: confirm a removed authorization check in `start_checkout` makes a test
  fail (per the project's "security guards were mutation-tested" convention).

## Open items for later sub-projects (not blocking this spec)

- `human_edit_requests` table shape, editor workflow/assignment, and retention wiring: sub-project 2.
- AI enhancement derivative storage and retention: sub-project 3.
- Print vendor choice, shipping address PII handling, and size/price matrix: sub-project 4.
