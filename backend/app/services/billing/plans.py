"""The price list: one place for plans, prices and limits (pricing page, checkout, limits).

Prices are gross (incl. VAT): consumers must see the final price. They are EXAMPLE prices
until the owner sets real ones (`EXAMPLE_PRICES`); the pricing page says so.
"""

from dataclasses import dataclass
from typing import Literal

CURRENCY = "EUR"
VAT_RATE = 19  # percent, Germany
EXAMPLE_PRICES = True
SUBSCRIPTION_PERIOD_DAYS = 30

PlanKind = Literal["one_off", "subscription"]


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    kind: PlanKind
    price_cents: int  # gross, incl. VAT
    max_attendees: int  # per event
    max_photos: int  # per event
    events_per_period: int = 0  # subscriptions: events included per billing period


PLANS: dict[str, Plan] = {
    p.key: p
    for p in (
        Plan("event_s", "Event S", "one_off", 4_900, max_attendees=100, max_photos=500),
        Plan("event_m", "Event M", "one_off", 14_900, max_attendees=500, max_photos=3_000),
        Plan("event_l", "Event L", "one_off", 34_900, max_attendees=2_000, max_photos=10_000),
        # Events from the subscription get Event M limits.
        Plan("pro", "Pro", "subscription", 19_900, max_attendees=500, max_photos=3_000, events_per_period=5),
    )
}

PlanKey = Literal["event_s", "event_m", "event_l", "pro"]


def vat_part(gross_cents: int, rate: int = VAT_RATE) -> int:
    """The VAT contained in a gross amount, rounded to the cent."""
    return round(gross_cents * rate / (100 + rate))
