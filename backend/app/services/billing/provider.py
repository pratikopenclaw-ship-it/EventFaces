"""Payment providers. The app talks to one interface, so a real provider (e.g. Stripe
Checkout) can replace the fake one without touching orders or fulfilment:

1. `create_checkout(order)` → a session reference and the URL to send the customer to.
2. The provider confirms the outcome **server to server** (a webhook): `parse_confirmation`
   verifies its signature and freshness and returns a `Confirmation`. Only a verified
   confirmation can mark an order paid; the customer's browser never can.

`FakeProvider` is a test provider: its checkout is a TEST MODE page in this app that only
accepts published test card numbers, and it signs its confirmations exactly like a webhook
(HMAC-SHA256 over "timestamp.body", Stripe-style header). No real money moves.
"""

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.config import get_settings
from app.models import AddonOrder, Order

SIGNATURE_HEADER = "fake-signature"
TOLERANCE_SECONDS = 300  # a confirmation older (or newer) than this is refused: replay protection

# Published test cards (like Stripe's): the outcome is decided by the number. Anything
# else is refused before it is looked at further: this checkout must never see a real card.
TEST_CARDS: dict[str, str | None] = {
    "4242424242424242": None,  # succeeds
    "4000000000000002": "card_declined",
    "4000000000009995": "insufficient_funds",
}

ConfirmationType = Literal["checkout.completed", "checkout.payment_failed"]


class InvalidConfirmation(Exception):
    """Signature, timestamp or payload not acceptable (a forged or replayed request)."""


@dataclass(frozen=True)
class Checkout:
    session_ref: str
    url: str


@dataclass(frozen=True)
class Confirmation:
    event_id: str
    type: ConfirmationType
    session_ref: str
    amount_cents: int
    currency: str
    failure_code: str | None = None


class PaymentProvider(Protocol):
    name: str
    test_mode: bool

    def create_checkout(self, order: Order | AddonOrder) -> Checkout: ...

    def parse_confirmation(self, raw: bytes, headers: dict[str, str]) -> Confirmation: ...


def _sign(secret: str, timestamp: int, raw: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()


class FakeProvider:
    name = "fake"
    test_mode = True

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret

    @property
    def secret(self) -> str:
        return self._secret or get_settings().payments_webhook_secret

    def create_checkout(self, order: Order | AddonOrder) -> Checkout:
        ref = "fcs_" + secrets.token_urlsafe(24)
        if isinstance(order, AddonOrder):
            # Add-on orders have their own test-checkout API (/api/billing/addon-checkout/*),
            # so they need their own page. NOTE: the /checkout/addon/[session] frontend page
            # doesn't exist yet: this path is reserved for when the add-on checkout UI lands
            # (out of scope for this sub-project), mirroring /checkout/test/ for orders.
            return Checkout(session_ref=ref, url=f"/checkout/addon/{ref}")
        return Checkout(session_ref=ref, url=f"/checkout/test/{ref}")

    # --- the "provider side": what happens on its hosted page and its servers -----------

    def confirmation_for(self, order: Order | AddonOrder, card_number: str, now: float | None = None) -> tuple[bytes, dict[str, str]]:
        """Simulate the provider charging a test card; returns the signed webhook it sends.
        Raises ValueError for anything that isn't a test card (the number is never kept)."""
        digits = "".join(ch for ch in card_number if not ch.isspace())
        if digits not in TEST_CARDS:
            raise ValueError("not a test card")
        failure = TEST_CARDS[digits]
        payload = {
            "id": "evt_" + secrets.token_urlsafe(18),
            "type": "checkout.payment_failed" if failure else "checkout.completed",
            "data": {
                "session": order.provider_ref,
                "amount_total": order.amount_cents,
                "currency": order.currency.lower(),
                "failure_code": failure,
            },
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return raw, self.sign(raw, now)

    def sign(self, raw: bytes, now: float | None = None) -> dict[str, str]:
        ts = int(now if now is not None else time.time())
        return {SIGNATURE_HEADER: f"t={ts},v1={_sign(self.secret, ts, raw)}"}

    # --- our side: verifying what arrives ------------------------------------------------

    def parse_confirmation(self, raw: bytes, headers: dict[str, str], now: float | None = None) -> Confirmation:
        header = {k.lower(): v for k, v in headers.items()}.get(SIGNATURE_HEADER, "")
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        try:
            ts = int(parts["t"])
            given = parts["v1"]
        except (KeyError, ValueError):
            raise InvalidConfirmation("missing or malformed signature") from None
        current = now if now is not None else time.time()
        if abs(current - ts) > TOLERANCE_SECONDS:
            raise InvalidConfirmation("stale or future timestamp")
        if not hmac.compare_digest(_sign(self.secret, ts, raw), given):
            raise InvalidConfirmation("bad signature")
        try:
            body = json.loads(raw)
            data = body["data"]
            kind = body["type"]
            if kind not in ("checkout.completed", "checkout.payment_failed"):
                raise ValueError(kind)
            return Confirmation(
                event_id=str(body["id"])[:100],
                type=kind,
                session_ref=str(data["session"])[:100],
                amount_cents=int(data["amount_total"]),
                currency=str(data["currency"]).upper()[:3],
                failure_code=(str(data["failure_code"])[:40] if data.get("failure_code") else None),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise InvalidConfirmation("malformed payload") from e


_fake = FakeProvider()


def get_provider() -> FakeProvider:
    """The configured provider (PAYMENTS_PROVIDER; only the fake one exists so far)."""
    return _fake
